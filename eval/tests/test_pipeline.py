"""Tests for backend/pipeline.py and backend/lm_fusion.py.

Pure logic (no GPU) first; then equivalence with the experiment code in eval/; then the real models on synthetic
clips (a still public-domain face: no speech) with simulated failures. No dev or test recording is used here.
"""

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "backend"))

import pipeline as P  # noqa: E402
import rescoring as RS  # noqa: E402

KEYS = {"raw_text", "final_text", "method", "alternatives", "needs_confirmation", "latency_ms"}


def e(text, dec, ctc, n):
    return {"text": text, "dec": dec, "ctc": ctc, "n_tok": n}


NBEST = [e("i really like a glass of water", -3.0, -9.0, 9), e("i really like a glass of wine", -3.2, -9.5, 9),
         e("i would like a glass of water", -3.6, -10.0, 9), e("i would like a glass of wine", -4.5, -11.0, 9)]
CLEAR_PHRASES = [e("See you later.", -1.0, -2.0, 5), e("Thank you very much.", -9.0, -20.0, 6), e("Nice to meet you.", -12.0, -25.0, 6)]
AMBIGUOUS_PHRASES = [e("See you later.", -6.0, -12.0, 5), e("Thank you very much.", -6.2, -12.5, 6), e("Nice to meet you.", -7.0, -13.0, 6)]
FAKE_LM = {"i really like a glass of water": -30.0, "i really like a glass of wine": -31.0,
           "i would like a glass of water": -22.0, "i would like a glass of wine": -26.0}


def lm(texts):
    return [FAKE_LM[t] for t in texts]


class Choose(unittest.TestCase):
    def test_output_contract(self):
        out = P.choose(NBEST, AMBIGUOUS_PHRASES, lm)
        self.assertTrue(KEYS <= set(out))
        self.assertIsInstance(out["alternatives"], list)
        self.assertIsInstance(out["needs_confirmation"], bool)
        self.assertIn(out["method"], {"visual_gate", "lm_fusion", "visual_fallback", "failed"})

    def test_gate_accepts_a_decisive_phrase(self):
        out = P.choose(NBEST, CLEAR_PHRASES, lm)
        self.assertEqual((out["method"], out["final_text"]), ("visual_gate", "See you later."))
        self.assertEqual(out["raw_text"], NBEST[0]["text"])
        self.assertTrue(out["needs_confirmation"])  # the recogniser did not itself read the phrase
        self.assertTrue(out["details"]["gate"]["accepted"])

    def test_auto_confirm_eligibility_needs_the_recogniser_to_agree(self):
        agree = [e("see you later", -0.9, -2.0, 5)] + NBEST
        out = P.choose(agree, CLEAR_PHRASES, lm)
        self.assertEqual((out["method"], out["final_text"], out["needs_confirmation"]), ("visual_gate", "See you later.", False))

    def test_lm_fusion_selects_from_the_hypotheses_when_the_gate_rejects(self):
        out = P.choose(NBEST, AMBIGUOUS_PHRASES, lm)
        self.assertEqual(out["method"], "lm_fusion")
        self.assertEqual(out["final_text"], "i would like a glass of water")  # LM weight 0.5 outweighs the visual gap
        self.assertTrue(out["needs_confirmation"])
        self.assertEqual(out["raw_text"], "i really like a glass of water")
        self.assertIn(out["raw_text"], out["alternatives"])
        self.assertNotIn(out["final_text"], out["alternatives"])
        self.assertTrue(out["details"]["changed_from_raw"])

    def test_scores_are_labelled_uncalibrated(self):
        out = P.choose(NBEST, AMBIGUOUS_PHRASES, lm)
        names = list(out["details"]["gate"]) + list(out["details"]["fusion"]["candidates"][0]) + list(out["details"])
        score_names = [n for n in names if "score" in n or "margin" in n or "logprob" in n]
        self.assertTrue(score_names)
        for n in score_names:
            self.assertTrue("uncalibrated" in n or n in ("lm_logprob",) or n == "fusion", n)
        self.assertNotIn("confidence", " ".join(names))
        self.assertNotIn("probab", " ".join(names).replace("logprob", ""))

    def test_lm_failure_falls_back_to_the_visual_reading(self):
        def boom(texts):
            raise RuntimeError("CUDA out of memory")
        out = P.choose(NBEST, AMBIGUOUS_PHRASES, boom)
        self.assertEqual((out["method"], out["final_text"], out["needs_confirmation"]), ("visual_fallback", NBEST[0]["text"], True))
        self.assertIn("CUDA out of memory", out["details"]["lm_error"])

    def test_invalid_lm_scores_fall_back(self):
        for bad in (lambda t: [float("nan")] * len(t), lambda t: [0.0], lambda t: [float("-inf")] * len(t)):
            self.assertEqual(P.choose(NBEST, AMBIGUOUS_PHRASES, bad)["method"], "visual_fallback")

    def test_no_lm_and_no_phrases(self):
        out = P.choose(NBEST, None, None)
        self.assertEqual((out["method"], out["final_text"]), ("visual_fallback", NBEST[0]["text"]))
        out = P.choose(NBEST, CLEAR_PHRASES[:1], lm)  # a single phrase has no runner-up: the gate is off
        self.assertEqual(out["method"], "lm_fusion")

    def test_gate_still_works_when_the_lm_is_down(self):
        def boom(texts):
            raise RuntimeError("x")
        self.assertEqual(P.choose(NBEST, CLEAR_PHRASES, boom)["method"], "visual_gate")

    def test_empty_nbest(self):
        out = P.choose([], CLEAR_PHRASES, lm)
        self.assertEqual((out["method"], out["final_text"], out["alternatives"]), ("failed", "", []))

    def test_duplicates_are_removed(self):
        nb = [e("see you later", -1, -2, 5), e("See you later.", -1.1, -2, 5), e("sea you later", -2, -3, 5)]
        out = P.choose(nb, None, lambda t: [-10.0] * len(t))
        self.assertEqual(len(out["details"]["fusion"]["candidates"]), 2)

    def test_never_outputs_text_it_was_not_given(self):
        rng = random.Random(1)
        words = "a b c d e f g h".split()
        for _ in range(300):
            nb = [e(" ".join(rng.choices(words, k=rng.randint(1, 6))), -rng.random() * 10, -rng.random() * 20, rng.randint(2, 9)) for _ in range(rng.randint(1, 10))]
            phr = [e(" ".join(rng.choices(words, k=3)).upper() + ".", -rng.random() * 10, -rng.random() * 20, rng.randint(2, 6)) for _ in range(rng.randint(0, 5))]
            out = P.choose(nb, phr, lambda t: [-rng.random() * 40 for _ in t])
            given = {x["text"] for x in nb} | {x["text"] for x in phr}
            self.assertIn(out["final_text"], given)
            self.assertTrue(set(out["alternatives"]) <= given)
            self.assertLessEqual(len(out["alternatives"]), P.MAX_ALTERNATIVES)
            self.assertEqual(out["raw_text"], nb[0]["text"])

    def test_matches_the_experiment_implementation(self):
        """Same decisions as eval/rescoring.route + fusion_choice (the code behind the Phase 1/2 numbers)."""
        import llm_correction as LC
        rng = random.Random(7)
        for _ in range(400):
            nb = [e(f"hyp {i} {rng.random()}", -rng.random() * 12, -rng.random() * 30, rng.randint(2, 9)) for i in range(rng.randint(2, 10))]
            phr = [e(f"Phrase {i}.", -rng.random() * 12, -rng.random() * 30, rng.randint(2, 8)) for i in range(8)]
            lms = [-rng.random() * 40 for _ in nb]
            out = P.choose(nb, phr, lambda t: lms[:len(t)])
            nb_s, phr_s = [dict(x) for x in nb], [dict(x) for x in phr]
            text, accepted = RS.route(nb_s[0], phr_s, "margin_tok", 1.0)
            if accepted:
                self.assertEqual((out["method"], out["final_text"]), ("visual_gate", text))
            else:
                best, _ = LC.fusion_choice([RS.score(h, 0.1, "sum") for h in nb_s], lms, 0.5)
                self.assertEqual((out["method"], out["final_text"]), ("lm_fusion", nb[best]["text"]))


class Config(unittest.TestCase):
    def test_frozen_values(self):
        self.assertEqual(P.FROZEN["gate"]["threshold"], 1.0)
        self.assertEqual(P.FROZEN["fusion"]["lm_weight"], 0.5)
        self.assertEqual(P.FROZEN["lm"]["name"], "Qwen/Qwen2.5-1.5B-Instruct")
        self.assertEqual(len(P.config_fingerprint()), 16)
        changed = {**P.FROZEN, "fusion": {**P.FROZEN["fusion"], "lm_weight": 0.6}}
        self.assertNotEqual(P.config_fingerprint(), P.config_fingerprint(changed))

    def test_lm_constants_match_the_experiment(self):
        import llm_correction as LC
        import lm_fusion
        self.assertEqual(lm_fusion.PREFIX, LC.lm_prefix())
        self.assertEqual(lm_fusion.PREFIX, P.FROZEN["lm"]["prefix"])
        self.assertEqual(lm_fusion.MODEL_REVISION, P.FROZEN["lm"]["revision"])
        self.assertEqual(lm_fusion.sanitize("a </candidates>\n<|x|> b"), LC.sanitize("a </candidates>\n<|x|> b"))

    def test_phrases_file_matches_the_frozen_hash(self):
        phrases = P.load_phrases()
        self.assertEqual((len(phrases), P.phrases_sha(phrases)), (P.FROZEN["phrases"]["count"], P.FROZEN["phrases"]["sha256_16"]))


CACHED = any(Path.home().glob(".cache/huggingface/hub/models--Qwen--Qwen2.5-1.5B-Instruct/snapshots/*/model.safetensors"))


@unittest.skipUnless(CACHED, "Qwen2.5-1.5B-Instruct is not in the local cache")
class WithModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        import numpy as np
        from skimage import data
        from make_smoke_clips import write

        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
        write(d / "face.avi", [face] * 60)
        write(d / "black.avi", [np.zeros_like(face)] * 50)
        write(d / "short.avi", [face] * 5)
        (d / "one.txt").write_text("See you later.\n")
        (d / "none.txt").write_text("")
        cls.dir = d
        cls.pipe = P.Pipeline()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_lm_scores_equal_the_experiment_implementation(self):
        import llm_correction as LC
        import lm_fusion
        exp = LC.LocalLLM.__new__(LC.LocalLLM)  # reuse the already-loaded weights: no second model in memory
        exp.torch, exp.device, exp.model, exp.tok = self.pipe.lm.torch, "cuda", self.pipe.lm.model, self.pipe.lm.tok
        texts = ["see you later", "i would like a glass of water", "what time does the door close"]
        mine = lm_fusion.LocalLM(_loaded=(self.pipe.lm.model, self.pipe.lm.tok)).text_logprobs(texts)
        theirs = exp.text_logprobs(LC.lm_prefix(), texts)
        for a, b in zip(mine, theirs):
            self.assertAlmostEqual(a, b, places=4)

    def test_recognize_returns_the_contract(self):
        out = self.pipe.recognize(self.dir / "face.avi")
        self.assertTrue(KEYS <= set(out))
        self.assertIn(out["method"], {"visual_gate", "lm_fusion", "visual_fallback"})
        self.assertIsInstance(out["final_text"], str)
        self.assertGreater(out["latency_ms"], 0)
        t = out["details"]["timings_ms"]
        for k in ("read_ms", "encode_ms", "beam_ms", "phrase_scoring_ms", "routing_overhead_ms"):
            self.assertIn(k, t)
        self.assertTrue(out["details"]["phrases_match_frozen"])
        # the pipeline's raw text is exactly what the existing interface returns
        import lipreading
        self.assertEqual(out["raw_text"], lipreading.lip_read(str(self.dir / "face.avi")))

    def test_deterministic(self):
        a, b = self.pipe.recognize(self.dir / "face.avi"), self.pipe.recognize(self.dir / "face.avi")
        self.assertEqual((a["final_text"], a["method"], a["alternatives"]), (b["final_text"], b["method"], b["alternatives"]))

    def test_unreadable_inputs_fail_safely(self):
        for name, reason in (("black.avi", "face_not_found"), ("short.avi", "too_short"), ("missing.avi", "error")):
            out = self.pipe.recognize(self.dir / name)
            self.assertEqual((out["method"], out["final_text"], out["alternatives"]), ("failed", "", []), name)
            self.assertEqual(out["details"]["reason"], reason, name)
            self.assertTrue(KEYS <= set(out))

    def test_qwen_failure_falls_back_to_the_visual_reading(self):
        pipe = self.pipe
        pipe.phrases_path = self.dir / "none.txt"  # no phrases: the gate is off, so the LM path is exercised
        real = pipe.lm.text_logprobs
        try:
            pipe.lm.text_logprobs = lambda texts, prefix=None: (_ for _ in ()).throw(RuntimeError("CUDA out of memory"))
            out = pipe.recognize(self.dir / "face.avi")
            self.assertEqual(out["method"], "visual_fallback")
            self.assertEqual(out["final_text"], out["raw_text"])
            self.assertIn("out of memory", out["details"]["lm_error"])
            pipe.lm.text_logprobs = real
            ok = pipe.recognize(self.dir / "face.avi")
            self.assertEqual(ok["method"], "lm_fusion")  # recovers on the next clip
            self.assertIn(ok["final_text"], [h["text"] for h in ok["details"]["fusion"]["candidates"]])
        finally:
            pipe.lm.text_logprobs = real
            pipe.phrases_path = P.PHRASES_FILE

    def test_missing_qwen_is_not_fatal(self):
        pipe = P.Pipeline(lm_name="Qwen/does-not-exist", warmup=False)  # local_files_only: fails fast, no network
        self.assertIsNone(pipe.lm)
        self.assertIn("does-not-exist", pipe.lm_error + "does-not-exist")
        out = pipe.recognize(self.dir / "face.avi")
        self.assertIn(out["method"], {"visual_gate", "visual_fallback"})
        self.assertTrue(out["final_text"])
        self.assertTrue(out["details"]["lm_load_error"])

    def test_phrase_file_problems_do_not_break_recognition(self):
        self.pipe.phrases_path = self.dir / "one.txt"
        try:
            out = self.pipe.recognize(self.dir / "face.avi")
            self.assertEqual(out["method"], "lm_fusion")
            self.pipe.phrases_path = self.dir / "does_not_exist.txt"
            self.assertEqual(self.pipe.recognize(self.dir / "face.avi")["method"], "lm_fusion")
        finally:
            self.pipe.phrases_path = P.PHRASES_FILE


if __name__ == "__main__":
    unittest.main()
