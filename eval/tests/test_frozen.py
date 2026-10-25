"""Tests for the frozen-configuration check and the final-test guards. Nothing here runs the test split."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import final_test as FT  # noqa: E402
import frozen as F  # noqa: E402


class Compare(unittest.TestCase):
    def setUp(self):
        self.state = F.current_state(with_model_hashes=False)

    def test_identical_state_passes(self):
        self.assertEqual(F.compare(self.state, copy.deepcopy(self.state)), ([], []))

    def test_changed_parameter_source_or_model_blocks(self):
        frozen = copy.deepcopy(self.state)
        frozen["models"] = {"qwen": {"revision": "r1"}}
        cases = [(lambda s: s.update(strategy_fingerprint="0" * 16), "strategy"),
                 (lambda s: s["sources"].update({"backend/pipeline.py": "x"}), "source file"),
                 (lambda s: s["models"].update({"qwen": {"revision": "r2"}}), "model")]
        for mutate, text in cases:
            current = copy.deepcopy(frozen)
            mutate(current)
            fatal, _ = F.compare(frozen, current)
            self.assertTrue(any(text in f for f in fatal), text)

    def test_library_version_is_only_a_warning(self):
        cur = copy.deepcopy(self.state)
        cur["libs"]["torch"] = "0.0.0"
        fatal, warn = F.compare(self.state, cur)
        self.assertEqual(fatal, [])
        self.assertTrue(any("torch" in w for w in warn))

    def test_verify_reads_a_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cfg.json"
            p.write_text(json.dumps(self.state))
            self.assertEqual(FT.verify(p, current=copy.deepcopy(self.state)), ([], []))
            bad = copy.deepcopy(self.state)
            bad["sources"]["backend/lipreading.py"] = "tampered"
            fatal, _ = FT.verify(p, current=bad)
            self.assertTrue(fatal)

    def test_frozen_strategy_values(self):
        s = self.state["strategy"]
        self.assertEqual((s["gate"]["threshold"], s["fusion"]["lm_weight"]), (1.0, 0.5))


class Guards(unittest.TestCase):
    def test_needs_the_explicit_flag(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(FT.check_guards(False, Path(d) / "lock"))
            self.assertEqual(FT.check_guards(True, Path(d) / "lock"), [])

    def test_refuses_a_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "lock"
            lock.write_text("started earlier\n")
            problems = FT.check_guards(True, lock)
            self.assertTrue(any("already been started" in p for p in problems))

    def test_cli_refuses_without_flag_and_creates_no_lock(self):
        import subprocess
        before = FT.LOCK.exists()
        r = subprocess.run([sys.executable, str(Path(FT.__file__)), "run", "/nonexistent/manifest.csv"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("single-final-run", r.stderr)
        self.assertEqual(FT.LOCK.exists(), before)
        self.assertFalse(FT.LOCK.exists())  # the final test has not been run

    def test_no_tuning_options_exist(self):
        import subprocess
        out = subprocess.run([sys.executable, str(Path(FT.__file__)), "run", "-h"], capture_output=True, text=True).stdout
        for banned in ("lambda", "lam", "threshold", "weight", "beam", "prompt"):
            self.assertNotIn("--" + banned, out)


if __name__ == "__main__":
    unittest.main()
