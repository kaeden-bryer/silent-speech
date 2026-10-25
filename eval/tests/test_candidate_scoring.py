"""Tests for lip_read_detailed / score_candidates. Loads the real model on the GPU (about 10 s).

    PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s eval/tests

Test video: the public-domain astronaut photo (scikit-image) as a still 25 fps clip, written to
a temp dir. It has no speech; the tests check the scoring maths and the interfaces, not accuracy.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # must precede the torch import

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "backend"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from skimage import data  # noqa: E402

import lipreading as L  # noqa: E402
from make_smoke_clips import write  # noqa: E402


def ctc_loglik(logp, target, blank=0):
    """Independent CTC forward algorithm in log space. logp: T x V numpy, target: list of ids."""
    ext = [blank]
    for t in target:
        ext += [t, blank]
    S, T = len(ext), logp.shape[0]
    neg = -np.inf
    alpha = np.full((T, S), neg)
    alpha[0, 0] = logp[0, ext[0]]
    if S > 1:
        alpha[0, 1] = logp[0, ext[1]]
    for t in range(1, T):
        for s in range(S):
            prev = [alpha[t - 1, s]]
            if s >= 1:
                prev.append(alpha[t - 1, s - 1])
            if s >= 2 and ext[s] != blank and ext[s] != ext[s - 2]:
                prev.append(alpha[t - 1, s - 2])
            alpha[t, s] = np.logaddexp.reduce(prev) + logp[t, ext[s]]
    return float(np.logaddexp(alpha[-1, -1], alpha[-1, -2]) if S > 1 else alpha[-1, -1])


def decoder_loglik_stepwise(enc, ids):
    """Independent decoder score: one forward_one_step call per token, as beam search does."""
    sos = eos = L.model.odim - 1
    total, prefix = 0.0, [sos]
    with torch.no_grad():
        for tok in ids + [eos]:
            ys = torch.tensor([prefix], device=L.DEVICE)
            mask = L.subsequent_mask(len(prefix), device=L.DEVICE).unsqueeze(0)
            logp, _ = L.model.decoder.forward_one_step(ys, mask, enc.unsqueeze(0))
            total += float(logp[0, tok])
            prefix.append(tok)
    return total


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
        write(d / "face.avi", [face] * 50)
        write(d / "black.avi", [np.zeros_like(face)] * 50)
        write(d / "short.avi", [face] * 5)
        cls.dir = d
        cls.result = L.lip_read_detailed(str(d / "face.avi"), debug_dir=str(d / "debug"))
        assert cls.result.reason == "ok", cls.result

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # -- tokenizer ---------------------------------------------------------------
    def test_normalize(self):
        self.assertEqual(L.normalize_for_scoring("Hello, how are you?"), "HELLO HOW ARE YOU")
        self.assertEqual(L.normalize_for_scoring("it’s  fine"), "IT'S FINE")
        self.assertEqual(L.normalize_for_scoring("?!  你好"), "")

    def test_uppercase_is_required_by_the_tokenizer(self):
        ids = L.tokenize_for_scoring("hello how are you")
        self.assertEqual(ids, [int(i) for i in L.text_transform.tokenize("HELLO HOW ARE YOU")])
        naive = [int(i) for i in L.text_transform.tokenize("hello how are you")]  # no uppercasing
        unk = int(L.text_transform.hashmap["<unk>"])
        self.assertNotIn(unk, ids)
        self.assertIn(unk, naive)  # the vocabulary is uppercase: lowercase words become <unk>
        self.assertGreater(len(naive), len(ids))

    # -- scoring maths --------------------------------------------------------------
    def test_rescoring_reproduces_beam_scores(self):
        r = self.result
        self.assertGreaterEqual(len(r.nbest), 3)
        for h in r.nbest[:5]:
            dec, ctc = L.score_token_sequences(r.encoder_out, [h.token_ids])
            self.assertAlmostEqual(dec[0], h.decoder_logprob, places=3)
            self.assertAlmostEqual(ctc[0], h.ctc_logprob, places=3)
            self.assertAlmostEqual(L.DECODER_WEIGHT * dec[0] + L.CTC_WEIGHT * ctc[0], h.score, places=3)

    def test_decoder_matches_stepwise_forward_one_step(self):
        for h in self.result.nbest[:3]:
            dec, _ = L.score_token_sequences(self.result.encoder_out, [h.token_ids])
            self.assertAlmostEqual(dec[0], decoder_loglik_stepwise(self.result.encoder_out, h.token_ids), places=3)

    def test_ctc_matches_independent_forward_algorithm(self):
        enc = self.result.encoder_out
        with torch.no_grad():
            logp = L.model.ctc.log_softmax(enc.unsqueeze(0))[0].double().cpu().numpy()
        for h in self.result.nbest[:3]:
            _, ctc = L.score_token_sequences(enc, [h.token_ids])
            self.assertAlmostEqual(ctc[0], ctc_loglik(logp, h.token_ids), places=2)

    def test_batching_does_not_change_scores(self):
        texts = ["See you later.", "Hello, how are you?", "I need more caffeine so badly right now", "Yes"]
        batch = L.score_candidates(self.result, texts)
        for text, b in zip(texts, batch):
            single = L.score_candidates(self.result, [text])[0]
            self.assertAlmostEqual(single.decoder_logprob, b.decoder_logprob, places=3)
            self.assertAlmostEqual(single.ctc_logprob, b.ctc_logprob, places=3)

    def test_text_candidates_use_uppercase_tokens(self):
        a = L.score_candidates(self.result, ["see you later"])[0]
        b = L.score_candidates(self.result, ["See you later!"])[0]
        self.assertEqual(a.token_ids, b.token_ids)
        self.assertEqual(a.unk_count, 0)
        self.assertAlmostEqual(a.score, b.score, places=4)

    def test_free_decode_beats_gibberish(self):
        best = self.result.nbest[0]
        free, gibberish = L.score_candidates(self.result, [best.text, "zqx jjk wvv qqz"])
        self.assertGreater(free.score, gibberish.score)
        self.assertGreater(free.score_per_token, gibberish.score_per_token)

    def test_scores_are_sums_so_longer_text_scores_lower(self):
        one, two = L.score_candidates(self.result, ["we're going to talk", "we're going to talk we're going to talk"])
        self.assertLess(two.score, one.score)  # documents why per-token / same-length comparison matters
        self.assertEqual(one.n_scored_tokens, len(one.token_ids) + 1)

    def test_empty_candidates_are_flagged_not_crashed(self):
        scores = L.score_candidates(self.result, ["", "   ", "?!", "See you later."])
        self.assertEqual([s.valid for s in scores], [False, False, False, True])
        self.assertTrue(all(s.score == float("-inf") for s in scores[:3]))
        self.assertTrue(np.isfinite(scores[3].score))
        self.assertEqual(L.score_candidates(self.result, []), [])

    def test_accepts_a_bare_encoder_tensor_and_rejects_none(self):
        s = L.score_candidates(self.result.encoder_out, ["see you later"])[0]
        self.assertTrue(np.isfinite(s.score))
        failed = L.lip_read_detailed(str(self.dir / "black.avi"))
        with self.assertRaises(ValueError):
            L.score_candidates(failed, ["see you later"])

    # -- detailed interface ---------------------------------------------------------
    def test_detailed_fields(self):
        r = self.result
        self.assertEqual(r.raw_text, r.nbest[0].text)
        self.assertEqual(r.frames.n_frames, 50)
        self.assertEqual(r.frames.n_detected, 50)
        self.assertEqual(r.frames.missing_frac, 0)
        self.assertEqual(r.n_enc_frames, 50)
        scores = [h.score for h in r.nbest]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLessEqual(len(r.nbest), L.NBEST_KEEP)
        for k in ("read_ms", "detect_ms", "roi_ms", "encode_ms", "beam_ms", "total_ms"):
            self.assertGreater(r.timings_ms[k], 0)
        self.assertGreaterEqual(r.timings_ms["total_ms"], sum(v for k, v in r.timings_ms.items() if k != "total_ms") * 0.99)
        self.assertAlmostEqual(r.nbest_margin, scores[0] - scores[1])
        json.dumps(r.to_dict())  # serialisable, no tensors

    def test_debug_image_written(self):
        self.assertTrue((self.dir / "debug" / "face_roi.png").stat().st_size > 1000)

    def test_failures_are_reported_not_raised(self):
        black = L.lip_read_detailed(str(self.dir / "black.avi"))
        self.assertEqual(black.reason, "face_not_found")
        self.assertEqual(black.frames.missing_frac, 1.0)
        self.assertEqual((black.raw_text, black.nbest), ("", []))
        short = L.lip_read_detailed(str(self.dir / "short.avi"))
        self.assertEqual((short.reason, short.raw_text), ("too_short", ""))
        missing = L.lip_read_detailed(str(self.dir / "nope.avi"))
        self.assertEqual(missing.reason, "error")

    # -- lip_read stays what the server expects --------------------------------------
    def test_lip_read_backward_compatible(self):
        text = L.lip_read(str(self.dir / "face.avi"))
        self.assertIsInstance(text, str)
        self.assertEqual(text, self.result.raw_text)
        self.assertEqual(L.lip_read(str(self.dir / "short.avi")), "")
        with self.assertRaisesRegex(ValueError, "face not found"):
            L.lip_read(str(self.dir / "black.avi"))
        with self.assertRaises(ValueError):
            L.lip_read(str(self.dir / "nope.avi"))

    def test_decode_and_find_face_keep_their_interfaces(self):
        self.assertIsInstance(L.decode(torch.randn(50, 1, 88, 88)), str)
        self.assertIsNone(L.find_face(np.zeros((240, 320, 3), np.uint8)))
        pts = L.find_face(data.astronaut())
        self.assertEqual(pts.shape, (4, 2))
        self.assertLess(pts[0, 0], pts[1, 0])  # keypoint 0 (subject's right eye) is on the image's left


if __name__ == "__main__":
    unittest.main()
