"""Baseline evaluation of the lip reader on a labelled manifest.

    python eval/evaluate.py manifest.csv [--out DIR] [--debug-roi-dir DIR] [--with-correction]

Run it with the venv that has the models (see models/MANIFEST.md), e.g.
    /home/asus/Github/silent-speech/.venv/bin/python eval/evaluate.py manifest.csv

manifest.csv has the columns video_path,text,category (paths relative to the manifest).
category is tags joined by +: silent | audible, and predefined | unseen | no_speech, e.g.
"silent+predefined". text is the ground truth exactly as spoken; leave it empty if you do not
have one (the clip is still run for latency, but not scored). See vsr_metrics.load_manifest.

Writes to --out (default eval/results/<timestamp>/, git-ignored because it holds transcripts):
    predictions.jsonl  one record per clip: raw text, n-best with scores, face stats, timings
    per_clip.csv       the same, flattened
    summary.json / summary.md   metrics per group (ALL, each tag, each full category)

Everything stays on this machine. The model is loaded only after the manifest validates.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # before torch is imported, see lipreading.py

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import vsr_metrics as M  # noqa: E402

PRIVATE_DIR = Path.home() / "sihyeon" / "data"  # recordings nobody has authorised for evaluation yet
STAGES = ["read_ms", "detect_ms", "roi_ms", "encode_ms", "beam_ms", "total_ms"]


def git_state():
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout.strip()
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "backend"))}
    except Exception:
        return None


def under(path, parent):
    try:
        Path(path).resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def evaluate_clip(L, row, correct, debug_dir):
    wall = time.perf_counter()
    result = L.lip_read_detailed(row["video_path"], debug_dir=debug_dir)
    wall_ms = (time.perf_counter() - wall) * 1000
    pred = result.raw_text
    out = dict(row)
    out.update({
        "clip": Path(row["video_path"]).name, "raw_text": pred, "reason": result.reason,
        "error": result.error or "", "wall_ms": wall_ms,
        "duration_s": result.frames.duration_s, "n_frames": result.frames.n_frames,
        "missing_frac": result.frames.missing_frac, "n_multi_face_frames": result.frames.n_multi_face_frames,
        "mean_det_score": result.frames.mean_det_score, "mouth_jitter": result.frames.mouth_jitter,
        "mean_face_width_frac": result.frames.mean_face_width_frac,
        "top_score": result.nbest[0].score if result.nbest else None,
        "top_score_per_token": result.nbest[0].score_per_token if result.nbest else None,
        "nbest_margin": result.nbest_margin,
        **{k: result.timings_ms.get(k) for k in STAGES},
    })
    out["rtf"] = out["total_ms"] / 1000 / out["duration_s"] if out["duration_s"] else None
    out["pred_norm"] = M.normalize_text(pred)
    if row["labeled"] and not row["no_speech"]:
        out.update(M.clip_metrics(row["text"], pred, [h.text for h in result.nbest]))
        if correct:
            fixed = correct(pred, []) if pred else ""
            m = M.clip_metrics(row["text"], fixed)
            out["corrected_text"] = fixed
            out["corrected_word_errors"], out["corrected_exact"] = m["word_errors"], m["exact"]
    else:
        out.update({"truth_norm": M.normalize_text(row["text"]), "ref_words": 0, "word_errors": 0, "subs": 0,
                    "dels": 0, "ins": 0, "ref_chars": 0, "char_errors": 0, "exact": 0, "oracle_word_errors": 0})
        if correct and pred:
            out["corrected_text"] = correct(pred, [])
    return out, result


def groups_of(rows):
    yield "ALL", rows
    for name in sorted({k for r in rows for k in M.group_keys(r)}):
        yield name, [r for r in rows if name in M.group_keys(r)]


def fmt(x, pct=False, nd=3):
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%" if pct else f"{x:.{nd}f}"


def _own(clip):
    if "closer_to_own" not in clip:
        return ""
    return "tie" if clip["closer_to_own"] is None else ("yes" if clip["closer_to_own"] else "no")


def write_markdown(path, summary):
    lines = ["# VSR evaluation", "",
             f"manifest: `{summary['config']['manifest']}`  |  clips: {summary['n_clips']}  |  {summary['config']['started']}", "",
             f"model: `{summary['config']['checkpoint']}`, beam {summary['config']['beam_size']}, "
             f"{summary['config']['device']}, torch {summary['config']['torch']}, split: {summary['config']['split']}", "",
             "WER/CER are corpus-level over labelled speech clips; a clip with no prediction counts as all deletions.", "",
             "## Accuracy", "",
             "| group | clips | scored | unlabeled | WER | CER | exact | oracle n-best WER | failed | no-speech false alarms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, g in summary["groups"].items():
        lines.append(f"| {name} | {g['n_clips']} | {g['n_labeled_speech']} | {g['n_unlabeled']} | {fmt(g['wer'], True)} | "
                     f"{fmt(g['cer'], True)} | {fmt(g['exact_match'], True)} | {fmt(g['oracle_nbest_wer'], True)} | "
                     f"{g['n_failed']} | {fmt(g['no_speech_false_alarm_rate'], True)} ({g['n_no_speech']}) |")
    if any("corrected_wer" in g for g in summary["groups"].values()):
        lines += ["", "## With the current fuzzy matcher (correction.correct)", "", "| group | WER | exact |", "|---|---|---|"]
        for name, g in summary["groups"].items():
            if "corrected_wer" in g:
                lines.append(f"| {name} | {fmt(g['corrected_wer'], True)} | {fmt(g['corrected_exact_match'], True)} |")
    lines += ["", "## Latency (ms, `lip_read_detailed`, model already warm)", "",
              "| stage | mean | p50 | p95 | max |", "|---|---|---|---|---|"]
    for stage, s in summary["latency_ms"].items():
        if s and stage != "rtf":
            lines.append(f"| {stage} | {s['mean']:.0f} | {s['p50']:.0f} | {s['p95']:.0f} | {s['max']:.0f} |")
    rtf = summary["latency_ms"].get("rtf")
    if rtf:
        lines.append(f"\nreal-time factor (total / clip duration): mean {rtf['mean']:.2f}, p95 {rtf['p95']:.2f}")
    if summary.get("pairs"):
        lines += ["", "## Paired clips (audible vs silent, contrast pairs)", "",
                  "| pair | clip | mode | truth | prediction | word errors | closer to own sentence |", "|---|---|---|---|---|---|---|"]
        for pr in summary["pairs"]:
            for c in pr["clips"]:
                lines.append(f"| {pr['pair_id']} | {c['clip_id']} | {c['speech_mode']} | {c['truth']} | {c['prediction']} | "
                             f"{c['word_errors']}/{c['ref_words']} | {_own(c)} |")
    if summary["failures"]:
        lines += ["", "## Failures", ""] + [f"- `{k}`: {v}" for k, v in summary["failures"].items()]
    if summary["warnings"]:
        lines += ["", "## Manifest warnings", ""] + [f"- {w}" for w in summary["warnings"]]
    Path(path).write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("--out", help="results directory (default eval/results/<timestamp>)")
    ap.add_argument("--debug-roi-dir", help="also write a local mouth-ROI contact sheet per clip here (shows faces)")
    ap.add_argument("--with-correction", action="store_true", help="also score correction.correct (the fuzzy matcher)")
    ap.add_argument("--warmup-runs", type=int, default=1, help="untimed passes over the first clip before measuring")
    ap.add_argument("--split", choices=["dev", "test", "all"],
                    help="which split to run. Default: dev when the manifest has a split column. The held-out test "
                         "split is for one final run: never tune thresholds, prompts or matching rules on it")
    ap.add_argument("--limit", type=int, help="only the first N rows")
    ap.add_argument("--authorized-data", action="store_true",
                    help=f"required to read clips under {PRIVATE_DIR}; only with explicit permission")
    args = ap.parse_args()

    phrases_file = ROOT / "backend" / "demo_phrases.txt"
    phrases = [p for p in phrases_file.read_text().splitlines() if p.strip()]
    try:
        rows, warnings = M.load_manifest(args.manifest, phrases)
    except (ValueError, OSError) as e:
        sys.exit(str(e))
    has_split = any(r.get("split") for r in rows)
    split = args.split or ("dev" if has_split else "all")
    if split != "all":
        if not has_split:
            sys.exit(f"--split {split}: this manifest has no split column")
        rows = [r for r in rows if r["split"] == split]
        if not rows:
            sys.exit(f"no rows in split {split!r}")
    if split in ("test", "all") and has_split:
        print("NOTE: this run includes the held-out TEST split. Report its numbers, but do not use them to tune "
              "thresholds, prompts or matching rules.", file=sys.stderr)
    if args.limit:
        rows = rows[: args.limit]
    private = [r["video_path"] for r in rows if under(r["video_path"], PRIVATE_DIR)]
    if private and not args.authorized_data:
        sys.exit(f"refusing: {len(private)} clip(s) are under {PRIVATE_DIR}, which has not been authorised for "
                 "evaluation. Pass --authorized-data once that is explicitly allowed.")
    absent = [r["video_path"] for r in rows if not Path(r["video_path"]).is_file()]
    if absent:
        sys.exit("missing video file(s):\n  " + "\n  ".join(absent))
    for w in warnings:
        print("warning:", w, file=sys.stderr)

    import torch  # noqa: E402  (after the manifest validated: loading the model takes a while)
    import lipreading as L  # noqa: E402

    correct = None
    if args.with_correction:
        from correction import correct  # noqa: E402

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(args.out) if args.out else HERE / "results" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(args.warmup_runs):
        L.lip_read_detailed(rows[0]["video_path"])

    results, details = [], []
    for i, row in enumerate(rows, 1):
        out, result = evaluate_clip(L, row, correct, args.debug_roi_dir)
        results.append(out)
        details.append({**{k: v for k, v in out.items() if k not in ("tags",)}, "lip_read": result.to_dict()})
        print(f"[{i}/{len(rows)}] {out['clip']} ({out['category']}): {out['raw_text']!r}"
              + (f"  truth={row['text']!r}" if row["text"] else "") + (f"  ERROR {out['error']}" if out["error"] else "")
              + f"  {out['total_ms']:.0f} ms")

    with open(out_dir / "predictions.jsonl", "w") as f:
        for d in details:
            f.write(json.dumps(d, default=str) + "\n")
    cols = [k for k in results[0] if k != "tags"] + [k for r in results for k in r if k not in results[0] and k != "tags"]
    cols = list(dict.fromkeys(cols))
    with open(out_dir / "per_clip.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    ckpt = L.CHECKPOINT
    summary = {
        "config": {
            "manifest": str(Path(args.manifest).resolve()), "started": started, "beam_size": L.BEAM_SIZE,
            "checkpoint": ckpt.name, "checkpoint_bytes": ckpt.stat().st_size, "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__, "git": git_state(), "warmup_runs": args.warmup_runs,
            "with_correction": bool(correct), "split": split,
        },
        "n_clips": len(results),
        "groups": {name: M.summarize_group(g) for name, g in groups_of(results)},
        "latency_ms": {**{s: M.latency_summary(results, s) for s in STAGES}, "wall_ms": M.latency_summary(results, "wall_ms"),
                       "rtf": M.latency_summary(results, "rtf")},
        "pairs": M.pair_report(results),
        "failures": {r["clip"]: r["error"] or r["reason"] for r in results if r["error"] or r["reason"] != "ok"},
        "warnings": warnings,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_markdown(out_dir / "summary.md", summary)
    print(f"\nwrote {out_dir}")
    print((out_dir / "summary.md").read_text())


if __name__ == "__main__":
    main()
