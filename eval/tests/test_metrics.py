"""Tests for vsr_metrics (no model needed):  python -m unittest discover -s eval/tests -t eval"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vsr_metrics as M  # noqa: E402


class Normalize(unittest.TestCase):
    def test_case_and_punctuation(self):
        self.assertEqual(M.normalize_text("Hello, how are you?"), "hello how are you")
        self.assertEqual(M.normalize_text("Let’s win Calhacks!"), "let's win calhacks")
        self.assertEqual(M.normalize_text("  well-known   'quoted' "), "well known quoted")
        self.assertEqual(M.normalize_text(None), "")
        self.assertEqual(M.normalize_text("?!"), "")

    def test_ground_truth_and_prediction_treated_alike(self):
        self.assertEqual(M.clip_metrics("Thank you very much.", "thank you VERY much")["word_errors"], 0)


class Errors(unittest.TestCase):
    def test_substitution_deletion_insertion(self):
        self.assertEqual(M.word_errors("a b c", "a x c"), (1, 1, 0, 0))
        self.assertEqual(M.word_errors("a b c", "a c"), (1, 0, 1, 0))
        self.assertEqual(M.word_errors("a b c", "a b x c"), (1, 0, 0, 1))
        self.assertEqual(M.word_errors("a b", ""), (2, 0, 2, 0))

    def test_cer(self):
        self.assertEqual(M.char_errors("kitten", "sitting"), 3)

    def test_oracle_picks_best_nbest(self):
        m = M.clip_metrics("see you later", "sea you later", nbest_texts=["see you later", "see you"])
        self.assertEqual((m["word_errors"], m["oracle_word_errors"]), (1, 0))


def row(truth, pred, **kw):
    r = {"labeled": True, "no_speech": False, "error": "", **kw}
    r.update(M.clip_metrics(truth, pred))
    return r


class Summaries(unittest.TestCase):
    def test_corpus_level_not_mean_of_clips(self):
        rows = [row("one", "wrong"), row("a b c d e f g h i j", "a b c d e f g h i j")]
        g = M.summarize_group(rows)
        self.assertAlmostEqual(g["wer"], 1 / 11)  # corpus level
        self.assertAlmostEqual(g["mean_clip_wer"], 0.5)
        self.assertAlmostEqual(g["exact_match"], 0.5)

    def test_failed_clip_counts_as_deletions(self):
        g = M.summarize_group([row("two words", "", error="boom")])
        self.assertEqual((g["wer"], g["n_failed"]), (1.0, 1))

    def test_no_speech_and_unlabelled_excluded_from_accuracy(self):
        quiet = {"labeled": True, "no_speech": True, "error": "", "pred_norm": "hello"}
        quiet2 = {"labeled": True, "no_speech": True, "error": "", "pred_norm": ""}
        unlabeled = {"labeled": False, "no_speech": False, "error": "", "pred_norm": "x"}
        g = M.summarize_group([quiet, quiet2, unlabeled])
        self.assertIsNone(g["wer"])
        self.assertEqual((g["n_labeled_speech"], g["n_unlabeled"], g["n_no_speech"]), (0, 1, 2))
        self.assertEqual(g["no_speech_false_alarm_rate"], 0.5)

    def test_percentile(self):
        self.assertEqual(M.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(M.percentile([0, 10], 95), 9.5)
        self.assertIsNone(M.percentile([], 50))


class Manifest(unittest.TestCase):
    def load(self, text, phrases=("Thank you very much.",)):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.csv"
            p.write_text(text)
            return M.load_manifest(p, phrases)

    def test_good_manifest(self):
        rows, warns = self.load("video_path,text,category\na.mp4,Thank you very much.,silent+predefined\n"
                                "b.mp4,,no_speech\nc.mp4,,audible|unseen\n")
        self.assertEqual([r["labeled"] for r in rows], [True, True, False])
        self.assertEqual(rows[0]["category"], "predefined+silent")
        self.assertTrue(rows[0]["video_path"].endswith("a.mp4") and rows[0]["video_path"].startswith("/"))
        self.assertEqual(len(warns), 1)  # c.mp4 has no ground truth

    def test_labels_are_never_invented(self):
        rows, _ = self.load("video_path,text,category\na.mp4,,silent+unseen\n")
        self.assertFalse(rows[0]["labeled"])

    def test_bad_rows_are_all_reported(self):
        with self.assertRaises(ValueError) as cm:
            self.load("video_path,text,category\na.mp4,hi,silent\nb.mp4,hi,silent+unseen+audible\n"
                      "c.mp4,oops,no_speech\nd.mp4,hi,whispered+unseen\n")
        msg = str(cm.exception)
        for line in ("m.csv:2", "m.csv:3", "m.csv:4", "m.csv:5"):
            self.assertIn(line, msg)

    def test_missing_columns(self):
        with self.assertRaises(ValueError):
            self.load("path,label\na,b\n")

    def test_predefined_unseen_consistency_warnings(self):
        _, warns = self.load("video_path,text,category\na.mp4,Something else,silent+predefined\n"
                             "b.mp4,thank you very much,silent+unseen\n")
        self.assertEqual(len(warns), 2)


if __name__ == "__main__":
    unittest.main()
