"""Tests for the recording plan, the recorder server and the manifest it writes (no GPU, no torch).

    python3 -m unittest discover -s eval/tests
"""

import csv
import json
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "eval" / "recorder"))

import plan as P  # noqa: E402
import server as S  # noqa: E402
import vsr_metrics as M  # noqa: E402

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


FAKE_VIDEO = b"\x1aE\xdf\xa3" + b"x" * 5000  # not a real video: the server only stores bytes


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.items = P.build_plan()
        self.phrases = {p.lower() for p in P.load_phrases()}

    def test_counts_match_the_design(self):
        self.assertEqual(len(self.items), 40)
        self.assertEqual(Counter(i["set"] for i in self.items),
                         {"predefined": 16, "unseen": 10, "contrast": 6, "no_speech": 4, "audible": 4})

    def test_predefined_are_the_demo_phrases_twice(self):
        pre = [i for i in self.items if i["set"] == "predefined"]
        self.assertEqual(Counter(i["text"] for i in pre), {p: 2 for p in P.load_phrases()})

    def test_new_sentences_are_not_demo_phrases(self):
        for i in self.items:
            if i["set"] in ("unseen", "contrast"):
                self.assertNotIn(i["text"].lower(), self.phrases, i["clip_id"])

    def test_unique_ids_and_stable_order(self):
        ids = [i["clip_id"] for i in self.items]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [i["clip_id"] for i in P.build_plan()])  # deterministic
        self.assertTrue(all(a["text"] != b["text"] or not a["text"] for a, b in zip(self.items, self.items[1:])))  # no sentence twice in a row
        self.assertTrue(all(i["speech_mode"] == "audible" for i in self.items[-4:]))

    def test_no_speech_has_a_labelled_empty_transcript(self):
        for i in self.items:
            if i["set"] == "no_speech":
                self.assertEqual((i["text"], i["label_status"], P.manifest_category(i)), ("", "no_speech", "no_speech"))
            else:
                self.assertTrue(i["text"])
                self.assertEqual(i["label_status"], "labeled")

    def test_splits_are_leak_free(self):
        unseen = {s: {i["text"] for i in self.items if i["set"] in ("unseen", "contrast") and i["split"] == s} for s in ("dev", "test")}
        self.assertFalse(unseen["dev"] & unseen["test"])  # no new sentence appears in both splits
        by_pair = {}
        for i in self.items:
            if i["set"] == "contrast":
                by_pair.setdefault(i["pair_id"], set()).add(i["split"])
        self.assertTrue(all(len(v) == 1 for v in by_pair.values()))  # a contrast pair never straddles
        for p in {i["text"] for i in self.items if i["set"] == "predefined"}:
            self.assertEqual(sorted(i["split"] for i in self.items if i["text"] == p and i["set"] == "predefined"), ["dev", "test"])
        self.assertEqual(Counter(i["split"] for i in self.items if i["set"] == "no_speech"), {"dev": 2, "test": 2})

    def test_audible_clips_are_paired_with_a_silent_clip_of_the_same_sentence(self):
        by_pair = {}
        for i in self.items:
            if i["pair_id"].startswith("audible"):
                by_pair.setdefault(i["pair_id"], []).append(i)
        self.assertEqual(len(by_pair), 4)
        for pair, members in by_pair.items():
            self.assertEqual(sorted(m["speech_mode"] for m in members), ["audible", "silent"], pair)
            self.assertEqual(len({m["text"] for m in members}), 1)
            self.assertEqual(len({m["split"] for m in members}), 1)

    def test_validator_catches_a_leaked_phrase(self):
        bad = [dict(i) for i in self.items]
        bad[[i["set"] for i in bad].index("unseen")]["text"] = P.load_phrases()[0]
        self.assertTrue(P.validate_plan(bad, self.phrases))


class ServerTests(unittest.TestCase):
    token = "t0ken"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.httpd, self.store = S.make_server(self.tmp.name, self.token, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def call(self, path, data=None, mime="video/webm", token=True):
        headers = {"X-Recorder-Token": self.token} if token else {}
        if data is not None:
            headers["Content-Type"] = mime
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def save(self, clip, speaker="spk01", **extra):
        q = "&".join([f"speaker={speaker}", f"clip_id={clip}"] + [f"{k}={v}" for k, v in extra.items()])
        return self.call("/api/save?" + q, FAKE_VIDEO)

    # -- auth / validation ------------------------------------------------------
    def test_requires_token(self):
        self.assertEqual(self.call("/api/plan?speaker=spk01", token=False)[0], 401)
        self.assertEqual(self.call("/api/save?speaker=spk01&clip_id=uns01", FAKE_VIDEO, token=False)[0], 401)
        self.assertEqual(self.call("/", token=False)[0], 401)
        self.assertEqual(self.call("/?token=wrong", token=False)[0], 403)
        self.assertFalse(list(Path(self.tmp.name).glob("spk01")))

    def test_page_served_with_token_and_has_no_external_resources(self):
        code, body = self.call("/")
        self.assertEqual(code, 200)
        html = body.decode()
        self.assertIn("MediaRecorder", html)
        self.assertIsNone(re.search(r"""(src|href|action)\s*=\s*["']?(https?:)?//""", html))  # no external loads
        self.assertIsNone(re.search(r"@import|url\(\s*[\"']?(https?:)?//|fetch\(\s*[\"']https?:|<script[^>]+src=|<link[^>]+href=", html))
        self.assertNotIn("XMLHttpRequest", html)

    def test_rejects_bad_ids_and_types(self):
        for speaker in ("../evil", "a b", "", "x" * 40):
            self.assertEqual(self.save("uns01", speaker=speaker.replace(" ", "%20"))[0], 400, speaker)
        self.assertEqual(self.save("../../etc/passwd")[0], 400)
        self.assertEqual(self.save("nope01")[0], 400)
        self.assertEqual(self.call("/api/save?speaker=spk01&clip_id=uns01", FAKE_VIDEO, mime="text/html")[0], 400)
        self.assertEqual(self.call("/api/save?speaker=spk01&clip_id=uns01", b"tiny")[0], 400)
        self.assertEqual(list(Path(self.tmp.name).glob("spk01/clips/*")), [])

    # -- saving ------------------------------------------------------------------
    def test_save_names_files_consistently_and_writes_manifest(self):
        code, body = self.save("pre03_t1", duration="3.2", attempts=2)
        self.assertEqual(code, 200, body)
        self.assertTrue((Path(self.tmp.name) / "spk01" / "clips" / "spk01_pre03_t1_silent.webm").read_bytes() == FAKE_VIDEO)
        self.save("nos01")
        self.save("aud01")
        rows = read_csv(Path(self.tmp.name) / "spk01" / "manifest.csv")
        by = {r["clip_id"]: r for r in rows}
        self.assertEqual(set(by), {"pre03_t1", "nos01", "aud01"})
        self.assertEqual(by["pre03_t1"]["video_path"], "clips/spk01_pre03_t1_silent.webm")
        self.assertEqual((by["pre03_t1"]["category"], by["pre03_t1"]["split"], by["pre03_t1"]["speaker_id"]),
                         ("silent+predefined", "dev", "spk01"))
        self.assertEqual((by["pre03_t1"]["duration_s"], by["pre03_t1"]["attempts"]), ("3.2", "2"))
        self.assertEqual(by["aud01"]["video_path"], "clips/spk01_aud01_audible.webm")
        # the no-speech clip: labelled, empty transcript
        self.assertEqual((by["nos01"]["text"], by["nos01"]["label_status"], by["nos01"]["category"]), ("", "no_speech", "no_speech"))
        self.assertTrue((Path(self.tmp.name) / "manifest_all.csv").exists())

    def test_never_overwrites(self):
        self.assertEqual(self.save("uns01")[0], 200)
        code, body = self.save("uns01")
        self.assertEqual(code, 409)
        self.assertEqual(len(list((Path(self.tmp.name) / "spk01" / "clips").glob("*.webm"))), 1)
        # an explicit re-record keeps the old take
        self.assertEqual(self.call("/api/save?speaker=spk01&clip_id=uns01&replace=1", FAKE_VIDEO + b"v2")[0], 200)
        old = list((Path(self.tmp.name) / "spk01" / "superseded").glob("*uns01*"))
        self.assertEqual(len(old), 2)  # video + meta
        self.assertEqual(len(list((Path(self.tmp.name) / "spk01" / "clips").glob("*.webm"))), 1)
        self.assertEqual(len(read_csv(Path(self.tmp.name) / "spk01" / "manifest.csv")), 1)

    def test_unmanaged_file_with_same_name_is_not_clobbered(self):
        clips = Path(self.tmp.name) / "spk01" / "clips"
        clips.mkdir(parents=True)
        (clips / "spk01_uns01_silent.webm").write_bytes(b"precious")
        self.assertEqual(self.save("uns01")[0], 200)
        self.assertEqual((clips / "spk01_uns01_silent.webm").read_bytes(), b"precious")
        self.assertEqual(len(list(clips.glob("*.webm"))), 2)

    def test_plan_endpoint_reports_saved_clips(self):
        self.save("uns02")
        code, body = self.call("/api/plan?speaker=spk01")
        data = json.loads(body)
        self.assertEqual((code, len(data["items"]), list(data["saved"])), (200, 40, ["uns02"]))
        self.assertEqual(self.call("/api/clip?speaker=spk01&clip_id=uns02")[1], FAKE_VIDEO)
        self.assertEqual(self.call("/api/clip?speaker=spk02&clip_id=uns02")[0], 404)

    def test_speakers_are_kept_apart(self):
        self.save("uns01", speaker="spk01")
        self.save("uns01", speaker="spk02")
        self.assertEqual(len(read_csv(Path(self.tmp.name) / "manifest_all.csv")), 2)

    def test_refuses_the_old_recordings_directory(self):
        with self.assertRaises(SystemExit):
            S.Store(S.OLD_DATA)

    # -- compatibility with evaluate.py ----------------------------------------------
    def test_manifest_loads_in_evaluate_parser(self):
        for item in self.store.items:
            self.assertEqual(self.save(item["clip_id"])[0], 200, item["clip_id"])
        rows, warns = M.load_manifest(Path(self.tmp.name) / "spk01" / "manifest.csv", P.load_phrases())
        self.assertEqual(len(rows), 40)
        self.assertEqual(warns, [])  # no unlabelled rows, no predefined/unseen mismatches
        self.assertEqual(Counter(r["split"] for r in rows), {"dev": 22, "test": 18})
        quiet = [r for r in rows if r["no_speech"]]
        self.assertEqual(len(quiet), 4)
        self.assertTrue(all(r["labeled"] and r["text"] == "" for r in quiet))  # labelled empty, not unlabelled
        self.assertTrue(all(Path(r["video_path"]).is_file() for r in rows))
        self.assertEqual(Counter(r["category"] for r in rows),
                         {"predefined+silent": 16, "silent+unseen": 16, "no_speech": 4, "audible+predefined": 2, "audible+unseen": 2})


class ParserExtensionTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.csv"
            p.write_text(text)
            return M.load_manifest(p, ["Hello."])

    H = "video_path,text,category,split,label_status,speech_mode\n"

    def test_new_columns_pass_through(self):
        rows, _ = self.load(self.H + "a.webm,Hello.,silent+predefined,dev,labeled,silent\nb.webm,,no_speech,test,no_speech,none\n")
        self.assertEqual([(r["split"], r["labeled"], r["no_speech"]) for r in rows], [("dev", True, False), ("test", True, True)])

    def test_unlabeled_is_distinct_from_labelled_empty(self):
        rows, warns = self.load(self.H + "a.webm,,silent+unseen,dev,unlabeled,silent\nb.webm,,no_speech,dev,no_speech,none\n")
        self.assertEqual([r["labeled"] for r in rows], [False, True])
        self.assertEqual(len(warns), 1)

    def test_contradictions_are_errors(self):
        for line in ("a.webm,,silent+unseen,dev,labeled,silent",           # says labeled but no text
                     "a.webm,hi,silent+unseen,dev,unlabeled,silent",        # says unlabeled but has text
                     "a.webm,hi,silent+unseen,dev,no_speech,silent",        # no_speech status on a speech row
                     "a.webm,,no_speech,dev,unlabeled,none",                # unlabeled status on a no_speech row
                     "a.webm,hi,silent+unseen,val,labeled,silent",          # bad split
                     "a.webm,hi,silent+unseen,dev,labeled,audible"):        # mode vs tag
            with self.assertRaises(ValueError, msg=line):
                self.load(self.H + line + "\n")

    def test_pair_report(self):
        def r(clip, pair, mode, truth, pred, set_="audible"):
            return {"clip_id": clip, "pair_id": pair, "speech_mode": mode, "labeled": True, "no_speech": False, "set": set_,
                    **M.clip_metrics(truth, pred)}
        rows = [r("c1a", "contrast01", "silent", "I can come", "i can come", "contrast"),
                r("c1b", "contrast01", "silent", "I cannot come", "i can come", "contrast"),
                r("p", "audible01", "silent", "see you later", "sea you later"),
                r("a", "audible01", "audible", "see you later", "see you later"),
                r("solo", "x", "silent", "hi", "hi")]
        rep = {p["pair_id"]: p["clips"] for p in M.pair_report(rows)}
        self.assertEqual(set(rep), {"contrast01", "audible01"})
        self.assertTrue(rep["contrast01"][0]["closer_to_own"])
        self.assertFalse(rep["contrast01"][1]["closer_to_own"])  # predicted the partner's sentence
        self.assertEqual([c["word_errors"] for c in rep["audible01"]], [1, 0])


if __name__ == "__main__":
    unittest.main()
