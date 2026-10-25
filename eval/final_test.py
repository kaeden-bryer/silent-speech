"""The single final evaluation of the frozen pipeline on the held-out TEST split. NOT TO BE RUN until the team decides.

    python eval/final_test.py verify                                   # check code/models/parameters against eval/frozen_config.json
    python eval/final_test.py run MANIFEST --single-final-run          # the one real test run

Design: no tuning parameter exists here. The strategy comes from backend/pipeline.py (hash-checked against
frozen_config.json); `run` refuses to start if anything differs, refuses a second run (lock file written BEFORE the first
clip is read, so a crashed run still counts), and only touches rows with split == test. Nothing from the test run may be
used to change thresholds, lambda, prompts, phrases or code; if a bug is found, record it and report the run as is.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import frozen as F

sys.path.insert(0, str(F.ROOT / "eval"))
CONFIG = F.ROOT / "eval" / "frozen_config.json"
LOCK = F.ROOT / "eval" / "results" / "FINAL_TEST.lock"


def verify(config_path=CONFIG, current=None):
    """(fatal, warnings). Reads hashes only."""
    frozen = json.loads(Path(config_path).read_text())
    return F.compare(frozen, current if current is not None else F.current_state())


def check_guards(single_final_run, lock_path=LOCK):
    """Reasons the run must not start (empty list = allowed)."""
    problems = []
    if not single_final_run:
        problems.append("pass --single-final-run to confirm this is the one and only test run")
    if Path(lock_path).exists():
        problems.append(f"{lock_path} exists: the final test has already been started ({Path(lock_path).read_text().strip()})")
    return problems


def run(args):
    problems = check_guards(args.single_final_run)
    if problems:
        sys.exit("refusing to run:\n  " + "\n  ".join(problems))
    fatal, warn = verify()
    if fatal:
        sys.exit("refusing to run: the frozen configuration no longer matches:\n  " + "\n  ".join(fatal))
    frozen = json.loads(CONFIG.read_text())
    manifest = Path(args.manifest)
    import hashlib
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != frozen["final_test"]["manifest_sha256"]:
        sys.exit("refusing to run: the manifest differs from the one recorded at freeze time")
    import vsr_metrics as M
    rows, _ = M.load_manifest(manifest, [])
    rows = [r for r in rows if r.get("split") == "test"]
    if not rows:
        sys.exit("no test rows")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(f"started {time.strftime('%Y-%m-%d %H:%M:%S')} on {len(rows)} test clips; frozen fingerprint {frozen['strategy_fingerprint']}\n")
    for w in warn:
        print("warning:", w, file=sys.stderr)

    import pipeline
    pipe = pipeline.get_pipeline()
    records = []
    for r in rows:
        out = pipe.recognize(r["video_path"])
        rec = {k: r.get(k, "") for k in ("clip_id", "set", "speech_mode", "split", "text")} | {
            "no_speech": r["no_speech"], "raw_text": out["raw_text"], "final_text": out["final_text"], "method": out["method"],
            "needs_confirmation": out["needs_confirmation"], "latency_ms": out["latency_ms"], "alternatives": out["alternatives"]}
        records.append(rec)
        print(f"{rec['clip_id']:12} {rec['method']:14} {rec['final_text']!r}")
    out_dir = F.ROOT / "eval" / "results" / "final_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "predictions.json").write_text(json.dumps({"frozen_fingerprint": frozen["strategy_fingerprint"], "records": records}, indent=1))
    scored = [x for x in records if x["text"] and not x["no_speech"]]
    stat = {}
    for name, group in (("all scored", scored), ("silent", [x for x in scored if x["speech_mode"] == "silent"]),
                        ("predefined", [x for x in scored if x["set"] == "predefined"]),
                        ("unseen+contrast", [x for x in scored if x["set"] in ("unseen", "contrast")]),
                        ("audible", [x for x in scored if x["speech_mode"] == "audible"])):
        for label, key in (("raw", "raw_text"), ("final", "final_text")):
            ms = [M.clip_metrics(x["text"], x[key]) for x in group]
            if ms:
                stat[f"{name} / {label}"] = {"n": len(ms), "wer": sum(m["word_errors"] for m in ms) / sum(m["ref_words"] for m in ms),
                                            "cer": sum(m["char_errors"] for m in ms) / sum(m["ref_chars"] for m in ms), "exact": sum(m["exact"] for m in ms)}
    quiet = [x for x in records if x["no_speech"]]
    stat["no_speech clips with non-empty output"] = f"{sum(bool(x['final_text']) for x in quiet)}/{len(quiet)}"
    (out_dir / "summary.json").write_text(json.dumps(stat, indent=1))
    print(json.dumps(stat, indent=1))
    print(f"\nwrote {out_dir}. Report these numbers as they are; do not tune on them.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    r = sub.add_parser("run")
    r.add_argument("manifest")
    r.add_argument("--single-final-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "verify":
        fatal, warn = verify()
        for w in warn:
            print("warning:", w)
        if fatal:
            sys.exit("MISMATCH:\n  " + "\n  ".join(fatal))
        print("frozen configuration verified: strategy, source files and model files match eval/frozen_config.json")
    else:
        run(args)


if __name__ == "__main__":
    main()
