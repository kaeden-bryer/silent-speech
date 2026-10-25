"""Tests for rescoring.py and the experiment's selection logic (no model, no GPU)."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rescoring as RS  # noqa: E402


def h(text, dec, ctc, n):
    return {"text": text, "dec": dec, "ctc": ctc, "n_tok": n}


class Scores(unittest.TestCase):
    def test_variants(self):
        e = h("a", -4.0, -10.0, 4)
        self.assertAlmostEqual(RS.score(e, 0.1, "sum"), 0.9 * -4 + 0.1 * -10)
        self.assertAlmostEqual(RS.score(e, 0.0, "sum"), -4.0)
        self.assertAlmostEqual(RS.score(e, 1.0, "sum"), -10.0)
        self.assertAlmostEqual(RS.score(e, 0.1, "tok"), RS.score(e, 0.1, "sum") / 4)
        self.assertAlmostEqual(RS.score(e, 0.1, "sqrt"), RS.score(e, 0.1, "sum") / 2)
        with self.assertRaises(ValueError):
            RS.score(e, 0.1, "bogus")

    def test_baseline_rerank_never_changes_a_beam_ordered_list(self):
        # a list already sorted by the beam's own score: re-ranking with the same formula is a no-op
        nbest = sorted([h("x", -5, -9, 5), h("y", -4, -20, 4), h("z", -6, -8, 6)], key=lambda e: -RS.score(e))
        self.assertIs(RS.rerank(nbest), nbest[0])

    def test_length_normalisation_can_flip_the_choice(self):
        short = h("short", -3.0, -6.0, 2)   # sum -3.3, per-token -1.65
        long_ = h("long a b c", -5.0, -9.0, 8)  # sum -5.4, per-token -0.675
        self.assertEqual(RS.rerank([short, long_], 0.1, "sum")["text"], "short")
        self.assertEqual(RS.rerank([short, long_], 0.1, "tok")["text"], "long a b c")

    def test_ctc_weight_can_flip_the_choice(self):
        a = h("attention likes", -2.0, -30.0, 3)
        b = h("ctc likes", -4.0, -10.0, 3)
        self.assertEqual(RS.rerank([a, b], 0.0)["text"], "attention likes")
        self.assertEqual(RS.rerank([a, b], 1.0)["text"], "ctc likes")

    def test_empty_nbest(self):
        self.assertIsNone(RS.rerank([]))
        self.assertEqual(RS.phrase_choice([]), (None, None))


class Routing(unittest.TestCase):
    phrases = [h("See you later.", -6.0, -12.0, 5), h("Thank you very much.", -9.0, -20.0, 6), h("Nice to meet you.", -12.0, -25.0, 6)]

    def test_features(self):
        free = h("see you later", -5.5, -11.0, 5)
        f = RS.routing_features(free, self.phrases)
        self.assertEqual(f["phrase"], "See you later.")
        self.assertAlmostEqual(f["gap_sum"], RS.score(free) - RS.score(self.phrases[0]))
        self.assertGreater(f["margin_sum"], 0)

    def test_gate_accepts_close_phrase_and_rejects_far_one(self):
        close = h("see you later", -5.9, -12.0, 5)
        far = h("something completely different here", -3.0, -6.0, 6)  # free decode explains the video far better
        self.assertEqual(RS.route(close, self.phrases, "gap_sum", 2), ("See you later.", True))
        text, accepted = RS.route(far, self.phrases, "gap_sum", 2)
        self.assertEqual((text, accepted), ("something completely different here", False))

    def test_threshold_zero_means_phrase_must_outscore_free(self):
        better_phrase_free = h("see you late", -7.0, -14.0, 5)  # worse than the phrase
        self.assertTrue(RS.route(better_phrase_free, self.phrases, "gap_sum", 0)[1])
        self.assertFalse(RS.route(h("x", -1.0, -2.0, 1), self.phrases, "gap_sum", 0)[1])

    def test_margin_gate(self):
        free = h("x", -1.0, -2.0, 1)
        self.assertTrue(RS.route(free, self.phrases, "margin_sum", 1)[1])
        self.assertFalse(RS.route(free, self.phrases, "margin_sum", 100)[1])

    def test_auroc(self):
        self.assertEqual(RS.auroc([3, 4], [1, 2]), 1.0)
        self.assertEqual(RS.auroc([1, 2], [3, 4]), 0.0)
        self.assertEqual(RS.auroc([1], [1]), 0.5)
        self.assertIsNone(RS.auroc([], [1]))


class LeaveOneOut(unittest.TestCase):
    def test_loo_picks_on_other_clips_and_prefers_first_on_ties(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import rescoring_experiment as X  # noqa: E402  (imports no torch at module level)
        clips = [{"clip_id": f"c{i}", "text": "a b", "labeled": True, "no_speech": False} for i in range(3)]
        out_fn = lambda c, v: "a b" if v == "good" else "x y"
        outs, chosen = X.loo(clips, ["bad", "good"], out_fn, set())
        self.assertEqual(set(chosen.values()), {"good"})
        self.assertTrue(all(o == "a b" for o in outs.values()))
        # all values equally good: the first (most conservative) is chosen
        same, chosen2 = X.loo(clips, ["first", "second"], lambda c, v: "a b", set())
        self.assertEqual(set(chosen2.values()), {"first"})

    def test_loo_penalises_phrases_on_no_speech(self):
        import rescoring_experiment as X
        clips = [{"clip_id": "n1", "text": "", "labeled": True, "no_speech": True},
                 {"clip_id": "n2", "text": "", "labeled": True, "no_speech": True},
                 {"clip_id": "s1", "text": "hi there", "labeled": True, "no_speech": False}]
        fn = lambda c, v: "hi there" if v == "permissive" else "nothing"
        _, chosen = X.loo(clips, ["strict", "permissive"], fn, {"hi there"})
        self.assertEqual(chosen["s1"], "strict")  # the two no-speech clips make 'permissive' cost more than it gains


if __name__ == "__main__":
    unittest.main()
