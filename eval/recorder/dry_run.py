"""End-to-end dry run of the recorder with SYNTHETIC clips (a still public-domain photo).

    /home/asus/Github/silent-speech/.venv/bin/python eval/recorder/dry_run.py [--evaluate]

Starts the real server on a temporary directory (never eval/dataset), "records" all 40 clips
through the HTTP API exactly as the page does, re-records one, checks the no-overwrite rule and
the manifest, and with --evaluate runs eval/evaluate.py on it. The videos contain no speech, so
any WER from this is meaningless: it only shows that the plumbing works.
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "eval"))

import cv2  # noqa: E402
from skimage import data  # noqa: E402

import plan as P  # noqa: E402
import server as S  # noqa: E402
import vsr_metrics as M  # noqa: E402

TOKEN = "dry-run-token"


def synthetic_video(path, seconds):
    face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP80"), 25, (512, 512))
    for _ in range(int(seconds * 25)):
        out.write(face)
    out.release()
    return path.read_bytes()


def call(base, path, data=None, mime="video/webm"):
    headers = {"X-Recorder-Token": TOKEN}
    if data is not None:
        headers["Content-Type"] = mime
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true", help="also run eval/evaluate.py on the dry-run manifest")
    ap.add_argument("--keep", help="keep the dry-run data in this (new) directory instead of a temp dir")
    args = ap.parse_args()
    root = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="ss_dry_run_"))
    if root.resolve() == S.DEFAULT_DATA.resolve() or S.DEFAULT_DATA.resolve() in root.resolve().parents:
        sys.exit("dry run must not write into eval/dataset")
    if root.exists() and any(root.iterdir()):
        sys.exit(f"{root} is not empty")
    root.mkdir(parents=True, exist_ok=True)
    httpd, store = S.make_server(root / "dataset", TOKEN, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")

    clips = {s: synthetic_video(root / f"synthetic_{s}s.webm", s) for s in (2, 3)}
    code, body = call(base, "/api/plan?speaker=dry01")
    items = json.loads(body)["items"]
    check("plan served", code == 200 and len(items) == 40, f"({len(items)} clips)")
    for n, it in enumerate(items):
        q = f"speaker=dry01&clip_id={it['clip_id']}&duration={2 + n % 2}&attempts=1"
        code, body = call(base, "/api/save?" + q, clips[2 + n % 2])
        if code != 200:
            check(f"save {it['clip_id']}", False, body.decode())
    sdir = root / "dataset" / "dry01"
    check("40 clips written", len(list((sdir / "clips").glob("*.webm"))) == 40)
    check("duplicate save refused (409)", call(base, "/api/save?speaker=dry01&clip_id=uns01", clips[2])[0] == 409)
    check("re-record keeps the old take",
          call(base, "/api/save?speaker=dry01&clip_id=uns01&replace=1&attempts=2", clips[3])[0] == 200
          and len(list((sdir / "superseded").glob("*uns01*"))) == 2 and len(list((sdir / "clips").glob("*.webm"))) == 40)
    check("no token, no access", _status(base + "/api/plan?speaker=dry01") == 401)

    rows, warnings = M.load_manifest(sdir / "manifest.csv", P.load_phrases())
    check("manifest parses with evaluate.py's parser", len(rows) == 40 and not warnings, f"(warnings: {warnings})")
    print("  sets:", dict(Counter(r["set"] for r in rows)))
    print("  splits:", dict(Counter(r["split"] for r in rows)))
    quiet = [r for r in rows if r["no_speech"]]
    check("no-speech clips: labelled, empty transcript", len(quiet) == 4 and all(r["labeled"] and r["text"] == "" for r in quiet))
    check("every video exists", all(Path(r["video_path"]).is_file() for r in rows))
    with open(sdir / "manifest.csv", newline="") as f:
        print("  manifest columns:", next(csv.reader(f)))

    ok = all(checks)
    if args.evaluate:
        out = root / "eval_results"
        cmd = [sys.executable, str(ROOT / "eval" / "evaluate.py"), str(sdir / "manifest.csv"), "--out", str(out / "default"), "--with-correction"]
        env = {"PYTHONDONTWRITEBYTECODE": "1", "TORCH_DISABLE_NATIVE_JIT": "1", "PATH": "/usr/bin:/bin"}
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        summary = json.loads((out / "default" / "summary.json").read_text()) if (out / "default" / "summary.json").exists() else {}
        check("evaluate.py (default) ran on dev only", r.returncode == 0 and summary.get("config", {}).get("split") == "dev"
              and summary.get("n_clips") == 22, f"(n_clips={summary.get('n_clips')})")
        r2 = subprocess.run(cmd[:3] + ["--out", str(out / "test"), "--split", "test", "--limit", "2"], capture_output=True, text=True, env=env)
        check("evaluate.py --split test prints the held-out warning", r2.returncode == 0 and "held-out TEST" in r2.stderr)
        print((out / "default" / "summary.md").read_text() if (out / "default" / "summary.md").exists() else r.stderr[-2000:])
        ok = all(checks)
    httpd.shutdown()
    print(f"\ndry-run data: {root}" + ("" if args.keep else "  (temporary; delete it with rm -rf)"))
    print("DRY RUN " + ("PASSED" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def _status(url):
    try:
        return urllib.request.urlopen(url).status
    except urllib.error.HTTPError as e:
        return e.code


if __name__ == "__main__":
    main()
