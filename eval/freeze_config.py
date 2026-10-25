"""Write eval/frozen_config.json: the exact strategy, model versions and file hashes for the final held-out evaluation.

    python eval/freeze_config.py [--dev-results eval/results/pipeline_dev/cache_eval.json] [--manifest eval/dataset/spk01/manifest.csv]

Reads only hashes of code and model files, the dev results summary, and the text of the manifest (to hash it): no recording is opened.
Re-running overwrites the file; do it only deliberately, since the final test checks the hashes recorded here.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

import frozen as F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-results", default=str(F.ROOT / "eval/results/pipeline_dev/cache_eval.json"))
    ap.add_argument("--manifest", default=str(F.ROOT / "eval/dataset/spk01/manifest.csv"))
    ap.add_argument("--out", default=str(F.ROOT / "eval/frozen_config.json"))
    args = ap.parse_args()
    state = F.current_state()
    dev = json.loads(Path(args.dev_results).read_text())
    manifest = Path(args.manifest)
    state.update({
        "frozen_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git": F.git_info(),
        "hardware": F.gpu_info(),
        "dev_result_at_freeze": {"silent_wer": dev["silent"]["wer"], "silent_cer": dev["silent"]["cer"], "silent_exact": f"{dev['silent']['exact']}/17",
                                 "note": "17 silent dev clips of one speaker; chosen parameters were fixed before this number was computed"},
        "final_test": {"manifest": str(manifest.relative_to(F.ROOT)), "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                       "split": "test", "status": "NOT RUN",
                       "protocol": "run eval/final_test.py once; it verifies these hashes, refuses to run twice (lock file), and takes no tuning parameters"},
    })
    Path(args.out).write_text(json.dumps(state, indent=2))
    print(f"wrote {args.out}  (strategy fingerprint {state['strategy_fingerprint']}, {len(state['sources'])} source hashes, "
          f"{len(state['models'])} model entries)")
    if state["git"]["uncommitted_files"]:
        print("note: the working tree has uncommitted changes; the file hashes above pin the exact code, but committing before the final test "
              "would also pin it in git history.")


if __name__ == "__main__":
    main()
