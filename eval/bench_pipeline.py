"""Phase 3: evaluate and benchmark the frozen pipeline (backend/pipeline.py) on the DEV split only.

    python eval/bench_pipeline.py cache-eval  CACHE_JSON LLM_OUTPUTS_JSON --out DIR   # no GPU: the frozen decision on cached scores
    python eval/bench_pipeline.py live MANIFEST --out DIR [--cache CACHE_JSON]        # GPU: the real pipeline on the dev videos

cache-eval applies pipeline.choose (the production decision code, frozen lambda=0.5 and gate threshold 1.0) to the
Auto-AVSR scores and Qwen log-probs cached in Phase 1/2, and reports WER/CER/exact and the regression cases.
live runs the whole pipeline on the dev recordings in a fresh process and measures loading, cold and warm latency by stage,
GPU memory, equivalence with the cached result, and failure/fallback behaviour. Test-split rows are refused.
"""

import argparse
import json
import os
import statistics as st
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # before torch, see lipreading.py
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import pipeline as P  # noqa: E402  (pure python until a Pipeline is built)
import rescoring_experiment as X  # noqa: E402
import vsr_metrics as M  # noqa: E402


def fmt(x):
    return f"{x * 100:.1f}%"


def stats(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return {"n": len(v), "mean": st.mean(v), "median": st.median(v), "p95": v[int(0.95 * (len(v) - 1))], "max": v[-1]}


def stat_row(label, s):
    return f"| {label} | {s['n']} | {s['mean']:.0f} | {s['median']:.0f} | {s['p95']:.0f} | {s['max']:.0f} |" if s else f"| {label} | 0 | - | - | - | - |"


# =====================================================================================
# cache-eval
# =====================================================================================
def cache_eval(args):
    cache = json.loads(Path(args.cache).read_text())
    llm = json.loads(Path(args.llm).read_text())
    clips = cache["clips"]
    assert all(c["split"] == "dev" for c in clips)
    lm_cache = {o["clip_id"]: {h["text"]: lp for h, lp in zip(o["candidates"], o["lm_logprobs"])} for o in llm["outputs"]}
    phrase_set = X.norm_phrases(cache)
    subs = X.subsets(clips, phrase_set)
    scored = subs["all scored (20)"]
    silent = subs["silent (17)"]

    results, A, B = {}, {}, {}
    for c in clips:
        nbest = [{"text": h["text"], "dec": h["dec"], "ctc": h["ctc"], "n_tok": h["n_tok"]} for h in c["nbest"]]
        phrases = [{"text": p["text"], "dec": p["dec"], "ctc": p["ctc"], "n_tok": p["n_tok"]} for p in c["phrases"]]
        table = lm_cache[c["clip_id"]]
        results[c["clip_id"]] = P.choose(nbest, phrases, lambda texts, t=table: [t[x] for x in texts])
        A[c["clip_id"]] = nbest[0]["text"]
        B[c["clip_id"]] = P.choose(nbest, phrases, None)["final_text"] if results[c["clip_id"]]["method"] == "visual_gate" else nbest[0]["text"]
    H = {cid: r["final_text"] for cid, r in results.items()}

    L = []
    emit = L.append
    emit("# Frozen hybrid on the DEV cache\n")
    emit(f"Config `{P.FROZEN['version']}:{P.config_fingerprint()}`: visual phrase gate (margin per token >= {P.FROZEN['gate']['threshold']}) -> "
         f"Qwen likelihood fusion (lambda = {P.FROZEN['fusion']['lm_weight']}) -> final text. Computed by `pipeline.choose` (production code) from "
         "the Phase 1/2 cached scores; lambda and the gate threshold were fixed in advance and not revisited after seeing these numbers.\n")
    emit("| | silent WER | silent CER | silent exact | predefined (8) | unseen+contrast (9) | unseen only (5) | audible exact (3) | all scored WER (20) |\n|---|---|---|---|---|---|---|---|---|")
    metrics = {}
    for name, out in (("A raw Auto-AVSR", A), ("B visual gate only", B), ("**H hybrid (gate + LM fusion, lambda 0.5)**", H)):
        r = X.eval_outputs(clips, out, phrase_set)
        metrics[name] = r
        emit(f"| {name} | {fmt(r['silent (17)']['wer'])} | {fmt(r['silent (17)']['cer'])} | {r['silent (17)']['exact']}/17 | "
             f"{r['  silent predefined']['exact']}/8 (WER {fmt(r['  silent predefined']['wer'])}) | {r['  silent unseen+contrast']['exact']}/9 (WER {fmt(r['  silent unseen+contrast']['wer'])}) | "
             f"{r['  silent unseen only']['exact']}/5 | {r['audible (3)']['exact']}/3 | {fmt(r['all scored (20)']['wer'])} |")
    h = metrics["**H hybrid (gate + LM fusion, lambda 0.5)**"]
    emit("")
    emit(f"Exact numbers for H on the 17 silent clips: {h['silent (17)']['errors']} word errors / "
         f"{sum(M.clip_metrics(c['text'], '')['ref_words'] for c in silent)} reference words = WER {h['silent (17)']['wer'] * 100:.2f}%, "
         f"CER {h['silent (17)']['cer'] * 100:.2f}%, exact {h['silent (17)']['exact']}/17. On all 20 scored clips (incl. audible): "
         f"WER {h['all scored (20)']['wer'] * 100:.2f}%, CER {h['all scored (20)']['cer'] * 100:.2f}%, exact {h['all scored (20)']['exact']}/20.")
    d, ci, better, worse, same = X.paired_delta(silent, H, A)
    emit(f"Paired against A on the silent clips: {d * 100:+.1f} points (bootstrap 95% interval {ci[0] * 100:+.1f} to {ci[1] * 100:+.1f}); "
         f"{better} clips better, {worse} worse, {same} unchanged. Wrong predefined phrase on a non-phrase sentence: {len(h['wrong_phrase'])}; "
         f"phrase on a no-speech clip: {len(h['phrase_on_no_speech'])}.\n")
    emit("Reproducibility: the Phase 2 analysis reported E B + C2 lam=0.5 at silent WER 28.0%, exact 10/17. This run: "
         f"{h['silent (17)']['wer'] * 100:.1f}%, {h['silent (17)']['exact']}/17.\n")

    emit("## Which path each dev clip took\n")
    emit("| clip | truth | raw | final | method | needs confirmation | result |\n|---|---|---|---|---|---|---|")
    for c in clips:
        r = results[c["clip_id"]]
        verdict = "no speech" if c["no_speech"] else ("exact" if M.clip_metrics(c["text"], r["final_text"])["exact"] else f"{X.clip_errors(c, r['final_text'])} word errors")
        emit(f"| {c['clip_id']} | {c['text'] or '(none)'} | {r['raw_text'][:34]} | {r['final_text'][:34]} | {r['method']} | {r['needs_confirmation']} | {verdict} |")
    methods = [r["method"] for r in results.values()]
    auto = [c for c in clips if not results[c["clip_id"]]["needs_confirmation"]]
    emit(f"\nPaths: {methods.count('visual_gate')} visual gate, {methods.count('lm_fusion')} LM fusion (the LM runs only on those). "
         f"needs_confirmation=False for {len(auto)} clips ({', '.join(c['clip_id'] for c in auto)}); every one of them exact: "
         f"{all(M.clip_metrics(c['text'], results[c['clip_id']]['final_text'])['exact'] for c in auto if c['text'])}.\n")

    for title, base, label in (("Regression and improvement cases vs raw (A)", A, "raw"), ("Compared with the visual gate alone (B): what the LM fusion added", B, "gate only")):
        emit(f"## {title}\n")
        emit(f"| clip | truth | {label} | hybrid | word errors {label} -> hybrid | verdict |\n|---|---|---|---|---|---|")
        for c in clips:
            if M.normalize_text(H[c["clip_id"]]) == M.normalize_text(base[c["clip_id"]]):
                continue
            if c["no_speech"]:
                emit(f"| {c['clip_id']} | (no speech) | {base[c['clip_id']][:30]} | {H[c['clip_id']][:30]} | - | no-speech clip |")
                continue
            e0, e1 = X.clip_errors(c, base[c["clip_id"]]), X.clip_errors(c, H[c["clip_id"]])
            emit(f"| {c['clip_id']} | {c['text']} | {base[c['clip_id']]} | {H[c['clip_id']]} | {e0} -> {e1} | {'IMPROVED' if e1 < e0 else 'REGRESSION' if e1 > e0 else 'same errors'} |")
        emit("")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cache_eval.md").write_text("\n".join(L) + "\n")
    (out / "cache_eval.json").write_text(json.dumps({
        "config": P.FROZEN, "fingerprint": P.config_fingerprint(),
        "silent": {k: h["silent (17)"][k] for k in ("wer", "cer", "exact", "errors")},
        "all_scored": {k: h["all scored (20)"][k] for k in ("wer", "cer", "exact", "errors")},
        "outputs": {cid: {"final_text": r["final_text"], "method": r["method"], "needs_confirmation": r["needs_confirmation"]} for cid, r in results.items()},
    }, indent=1))
    print("\n".join(L))


# =====================================================================================
# live
# =====================================================================================
def nvidia_smi_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            pid, mem = [x.strip() for x in line.split(",")]
            if int(pid) == os.getpid():
                return float(mem)
    except Exception:
        pass
    return None


def live(args):
    rows, _ = M.load_manifest(args.manifest, [])
    if not any(r.get("split") for r in rows):
        sys.exit("manifest has no split column")
    rows = [r for r in rows if r["split"] == "dev"]
    assert rows and all(r["split"] == "dev" for r in rows)
    print(f"{len(rows)} dev clips (test split excluded)")
    report = {"n_clips": len(rows)}

    t = time.perf_counter()
    pipe = P.Pipeline(load_lm=True, warmup=False)  # no pipeline warm-up: the first clip below is a true cold call
    report["load_total_s"] = time.perf_counter() - t
    report["load_vsr_s"], report["load_lm_s"], report["lm_error"] = pipe.vsr_load_s, pipe.lm_load_s, pipe.lm_error
    import torch
    torch.cuda.synchronize()
    report["gpu_after_load_mib"] = pipe.lm.memory_mib()["allocated"]  # one process: Auto-AVSR + Qwen together
    report["smi_after_load_mib"] = nvidia_smi_mib()
    torch.cuda.reset_peak_memory_stats()

    # cold call on a clip that takes the LM path, so Qwen's first-use cost is inside the measurement
    methods_ref = json.loads(Path(args.cache).read_text())["outputs"] if args.cache else {}
    cold_row = next((r for r in rows if methods_ref.get(r["clip_id"], {}).get("method") == "lm_fusion"), rows[0])
    first = cold_row["video_path"]
    cold = pipe.recognize(first)
    pipe.warm_up()
    warm_again = pipe.recognize(first)
    report["cold_clip"] = cold_row["clip_id"]
    report["cold_first_call"] = {"latency_ms": cold["latency_ms"], "timings_ms": cold["details"]["timings_ms"], "method": cold["method"]}
    report["same_clip_second_call"] = {"latency_ms": warm_again["latency_ms"], "timings_ms": warm_again["details"]["timings_ms"], "method": warm_again["method"]}

    passes = []
    for p in range(2):
        recs = []
        for r in rows:
            out = pipe.recognize(r["video_path"])
            out["clip_id"] = r["clip_id"]
            recs.append(out)
        passes.append(recs)
        print(f"pass {p + 1}: mean {st.mean(o['latency_ms'] for o in recs):.0f} ms")
    warm = passes[1]
    report["peak_gpu_mib_during_run"] = pipe.lm.memory_mib()["peak"]
    report["smi_end_mib"] = nvidia_smi_mib()
    report["deterministic"] = all((a["final_text"], a["method"]) == (b["final_text"], b["method"]) for a, b in zip(*passes))

    t = lambda k: [o["details"]["timings_ms"].get(k) for o in warm]
    report["warm"] = {k: stats(t(k)) for k in ("read_ms", "detect_ms", "roi_ms", "encode_ms", "beam_ms", "total_ms", "phrase_scoring_ms",
                                               "lm_scoring_ms", "routing_overhead_ms")}
    report["warm"]["pipeline_latency_ms"] = stats([o["latency_ms"] for o in warm])
    report["warm"]["pass1_latency_ms"] = stats([o["latency_ms"] for o in passes[0]])
    by_method = {}
    for o in warm:
        by_method.setdefault(o["method"], []).append(o["latency_ms"])
    report["warm_by_method"] = {k: stats(v) for k, v in by_method.items()}

    # equivalence with the cached frozen decision, and accuracy of the live outputs
    truth = {r["clip_id"]: r for r in rows}
    live_out = {o["clip_id"]: o for o in warm}
    if args.cache:
        ref = json.loads(Path(args.cache).read_text())["outputs"]
        report["mismatch_vs_cache_eval"] = [(cid, ref[cid]["final_text"], live_out[cid]["final_text"]) for cid in ref
                                            if (ref[cid]["final_text"], ref[cid]["method"]) != (live_out[cid]["final_text"], live_out[cid]["method"])]
    sil = [r for r in rows if r["speech_mode"] == "silent" and not r["no_speech"]]
    ms = [M.clip_metrics(r["text"], live_out[r["clip_id"]]["final_text"]) for r in sil]
    report["live_silent"] = {"wer": sum(m["word_errors"] for m in ms) / sum(m["ref_words"] for m in ms),
                             "cer": sum(m["char_errors"] for m in ms) / sum(m["ref_chars"] for m in ms), "exact": sum(m["exact"] for m in ms), "n": len(ms)}
    report["methods"] = {m: sum(o["method"] == m for o in warm) for m in {o["method"] for o in warm}}

    # ---- failure and fallback behaviour (dev clip + synthetic clips in /tmp) ----------------------------
    fail = {}
    lm_clip = next(o["clip_id"] for o in warm if o["method"] == "lm_fusion")
    path = truth[lm_clip]["video_path"]
    base = pipe.recognize(path)
    real = pipe.lm.text_logprobs
    pipe.lm.text_logprobs = lambda texts, prefix=None: (_ for _ in ()).throw(RuntimeError("CUDA out of memory (simulated)"))
    o = pipe.recognize(path)
    pipe.lm.text_logprobs = real
    fail["qwen_scoring_error"] = {"clip": lm_clip, "method": o["method"], "final_equals_raw": o["final_text"] == o["raw_text"], "latency_ms": o["latency_ms"],
                                  "normal_latency_ms": base["latency_ms"], "needs_confirmation": o["needs_confirmation"], "lm_error": o["details"]["lm_error"]}
    again = pipe.recognize(path)
    fail["recovers_next_clip"] = again["method"] == base["method"] and again["final_text"] == base["final_text"]
    t0 = time.perf_counter()
    no_lm = P.Pipeline(load_lm=True, warmup=False, lm_name="Qwen/not-a-local-model")
    o = no_lm.recognize(path)
    fail["qwen_missing_at_startup"] = {"init_s": time.perf_counter() - t0, "method": o["method"], "final_equals_raw": o["final_text"] == o["raw_text"], "latency_ms": o["latency_ms"],
                                       "lm_error": (no_lm.lm_error or "")[:90]}
    import cv2, numpy as np  # noqa: E401
    from make_smoke_clips import write
    from skimage import data
    with tempfile.TemporaryDirectory() as d:
        face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
        write(Path(d) / "black.avi", [np.zeros_like(face)] * 50)
        write(Path(d) / "short.avi", [face] * 5)
        for name in ("black.avi", "short.avi", "missing.avi"):
            o = pipe.recognize(Path(d) / name)
            fail[name] = {"method": o["method"], "final_text": o["final_text"], "reason": o["details"]["reason"], "latency_ms": o["latency_ms"]}
        empty = Path(d) / "empty.txt"
        empty.write_text("")
        pipe.phrases_path = empty
        o = pipe.recognize(path)
        pipe.phrases_path = P.PHRASES_FILE
        fail["phrase_file_empty"] = {"method": o["method"], "final_text": o["final_text"], "latency_ms": o["latency_ms"]}
    report["failures"] = fail

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live.json").write_text(json.dumps({"report": report, "warm_records": [
        {k: v for k, v in o.items() if k != "details"} | {"timings_ms": o["details"]["timings_ms"], "gate": o["details"]["gate"]} for o in warm]}, indent=1, default=str))
    (out / "live.md").write_text(live_markdown(report, warm))
    print((out / "live.md").read_text())


def live_markdown(r, warm):
    w = r["warm"]
    L = ["# Live benchmark on the DEV recordings (fresh process, NVIDIA GB10)\n"]
    L.append("## Loading and memory\n")
    L.append(f"- Auto-AVSR + MediaPipe + warm-up decode (`import lipreading`): **{r['load_vsr_s']:.1f} s**")
    L.append(f"- Qwen2.5-1.5B-Instruct (local cache, bf16): **{r['load_lm_s']:.1f} s**; total pipeline construction {r['load_total_s']:.1f} s (one-off, at start-up)")
    L.append(f"- GPU memory allocated by this process after loading both models: **{r['gpu_after_load_mib']:.0f} MiB**; peak during {2 * r['n_clips']} recognitions: **{r['peak_gpu_mib_during_run']:.0f} MiB**")
    L.append(f"- nvidia-smi for this process: {r['smi_after_load_mib']} MiB after loading, {r['smi_end_mib']} MiB at the end (includes CUDA context and cache)")
    L.append("")
    c, s2 = r["cold_first_call"], r["same_clip_second_call"]
    L.append("## Cold vs warm\n")
    L.append("First `recognize` call in the process (no pipeline warm-up; Auto-AVSR itself is warmed by its own import) vs the same clip after `warm_up()`:\n")
    L.append("| stage ms | cold first call | same clip, warm |\n|---|---|---|")
    for k in ("read_ms", "detect_ms", "roi_ms", "encode_ms", "beam_ms", "phrase_scoring_ms", "lm_scoring_ms", "routing_overhead_ms"):
        a, b = c["timings_ms"].get(k), s2["timings_ms"].get(k)
        L.append(f"| {k} | {a:.0f} | {b:.0f} |" if a is not None and b is not None else f"| {k} | {a if a is None else round(a)} | {b if b is None else round(b)} |")
    L.append(f"| **whole call** | **{c['latency_ms']:.0f}** ({c['method']}) | **{s2['latency_ms']:.0f}** ({s2['method']}) |\n")
    L.append("## Warm latency over the dev clips (second pass; ms per clip)\n")
    L.append("| stage | n | mean | median | p95 | max |\n|---|---|---|---|---|---|")
    names = {"read_ms": "video read + resample", "detect_ms": "face detection (MediaPipe)", "roi_ms": "mouth ROI crop + transform", "encode_ms": "Auto-AVSR encoder",
             "beam_ms": "Auto-AVSR beam search (10-best)", "total_ms": "= Auto-AVSR path total", "phrase_scoring_ms": "visual gate: score the 8 phrases (encoder reused)",
             "lm_scoring_ms": "Qwen likelihood scoring (only when the gate rejects)", "routing_overhead_ms": "hybrid routing overhead (decision code, excluding Qwen)"}
    for k, label in names.items():
        L.append(stat_row(label, w[k]))
    L.append(stat_row("**whole `recognize()` call**", w["pipeline_latency_ms"]))
    L.append(stat_row("(first pass, for comparison)", w["pass1_latency_ms"]))
    L.append("")
    L.append("By path taken: " + "; ".join(f"{k}: n={v['n']}, mean {v['mean']:.0f} ms, max {v['max']:.0f} ms" for k, v in r["warm_by_method"].items()) + ".\n")
    L.append("## Consistency\n")
    L.append(f"- Two passes gave identical final texts and methods: **{r['deterministic']}**")
    mm = r.get("mismatch_vs_cache_eval")
    L.append(f"- Differences from the cached frozen decision (cache-eval): **{len(mm) if mm is not None else 'not checked'}** {mm if mm else ''}")
    ls = r["live_silent"]
    L.append(f"- Live silent WER {ls['wer'] * 100:.2f}%, CER {ls['cer'] * 100:.2f}%, exact {ls['exact']}/{ls['n']}; paths: {r['methods']}\n")
    L.append("## Failure and fallback behaviour\n")
    f = r["failures"]
    q = f["qwen_scoring_error"]
    L.append(f"- Qwen scoring raises an error (simulated CUDA OOM) on `{q['clip']}`: method `{q['method']}`, final text equals the raw reading: {q['final_equals_raw']}, "
             f"needs_confirmation={q['needs_confirmation']}, {q['latency_ms']:.0f} ms (normal {q['normal_latency_ms']:.0f} ms). Recovers on the next clip: {f['recovers_next_clip']}.")
    m = f["qwen_missing_at_startup"]
    L.append(f"- Qwen not available at start-up (init {m['init_s']:.2f} s, no network): clips are still recognised, method `{m['method']}`, final equals raw: {m['final_equals_raw']}, {m['latency_ms']:.0f} ms.")
    for name in ("black.avi", "short.avi", "missing.avi"):
        x = f[name]
        L.append(f"- `{name}` (no face / too short / unreadable): method `{x['method']}`, final text {x['final_text']!r}, reason `{x['reason']}`, {x['latency_ms']:.0f} ms.")
    x = f["phrase_file_empty"]
    L.append(f"- Empty demo_phrases.txt (gate disabled): method `{x['method']}`, {x['latency_ms']:.0f} ms.\n")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cache-eval")
    c.add_argument("cache")
    c.add_argument("llm")
    c.add_argument("--out", required=True)
    v = sub.add_parser("live")
    v.add_argument("manifest")
    v.add_argument("--out", required=True)
    v.add_argument("--cache", help="cache_eval.json from the cache-eval step, for the equivalence check")
    args = ap.parse_args()
    cache_eval(args) if args.cmd == "cache-eval" else live(args)


if __name__ == "__main__":
    main()
