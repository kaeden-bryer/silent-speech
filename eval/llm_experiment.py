"""Phase 2 experiment: local-LLM correction of lip-reading hypotheses, DEV split only.

    python eval/llm_experiment.py run CACHE_JSON --out DIR      # GPU: runs the local LLM, no ground truth in sight
    python eval/llm_experiment.py analyze CACHE_JSON DIR        # pure python: scores against the dev ground truth

CACHE_JSON is eval/results/rescoring_dev/cache.json from rescoring_experiment.py collect: the 10-best of
every dev clip with visual scores (dev clips only; no video is read here). `run` builds its inputs from
hypothesis texts and visual scores only and refuses non-loopback network access. Ground truth is
read only by `analyze`. No conversation history exists in the dev set (isolated, shuffled clips), so
every run here is the no-history experiment.

Methods (primary ones declared before looking at results: C1, D_raw, E = B + C1):
  A  raw Auto-AVSR                B  visual phrase gate (margin_tok >= 1.0, Phase 1)
  C1 LLM multiple choice (beam order, no scores)  [primary]   C1s with visual scores in the prompt   C1x averaged over reversed order
  C2 LM fusion: visual score + lam * LM log-prob (lam 0.25, 0.5, 1.0) and LM only
  D_raw  limited LLM edits of the raw top-1  [primary]   D_sel  limited edits of the C1 pick
  E  B first (phrase if the gate accepts), otherwise the method
"""

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))

import llm_correction as LC  # noqa: E402
import rescoring as RS  # noqa: E402
import rescoring_experiment as X  # noqa: E402
import vsr_metrics as M  # noqa: E402

LAMBDAS = (0.25, 0.5, 1.0)
GATE = ("margin_tok", 1.0)  # Phase 1's per-token margin gate, threshold chosen on dev there
FUSION_MARGIN = 1.0  # fusion: recommend confirmation if the top two fused scores are closer than this (nats)
PRIMARY = ("A raw", "B visual gate", "C1 LLM select", "D_raw LLM conservative", "E B + C1")


# =====================================================================================
# run (GPU)
# =====================================================================================
def timed(llm, fn):
    llm.torch.cuda.synchronize()
    t = time.perf_counter()
    out = fn()
    llm.torch.cuda.synchronize()
    return out, (time.perf_counter() - t) * 1000


def run(args):
    LC.block_network()
    cache = json.loads(Path(args.cache).read_text())
    assert all(c["split"] == "dev" for c in cache["clips"]), "dev clips only"
    # inputs: hypothesis texts and visual scores. Deliberately nothing else from the clip.
    inputs = [{"clip_id": c["clip_id"],
               "hyps": [{"text": h["text"], "sum": RS.score(h, 0.1, "sum"), "tok": RS.score(h, 0.1, "tok")} for h in c["nbest"]]}
              for c in cache["clips"]]

    t = time.perf_counter()
    llm = LC.LocalLLM()
    llm.torch.cuda.synchronize()
    load_s = time.perf_counter() - t
    mem_loaded = llm.memory_mib()
    LC.select_candidate(llm, inputs[0]["hyps"])  # CUDA warm-up, not measured
    LC.conservative_correct(llm, inputs[0]["hyps"])
    llm.torch.cuda.reset_peak_memory_stats()

    outputs = []
    for item in inputs:
        hyps, rec = item["hyps"], {"clip_id": item["clip_id"], "timings_ms": {}}
        cands = LC.dedupe(hyps)
        rec["candidates"] = [{"text": h["text"], "sum": h["sum"], "tok": h["tok"]} for h in cands]
        for name, kw in (("c1", {}), ("c1s", {"show_scores": True}), ("c1x", {"reverse_average": True})):
            (sel, info), ms = timed(llm, lambda kw=kw: LC.select_candidate(llm, hyps, **kw))
            rec[name] = {"index": sel.index, "text": sel.text, "option_probs": sel.option_probs, "confirm": sel.confirm,
                         "reasons": sel.reasons, **info}
            rec["timings_ms"][name] = ms
        lm, ms = timed(llm, lambda: llm.text_logprobs(LC.lm_prefix(), [h["text"] for h in cands]))
        rec["lm_logprobs"], rec["timings_ms"]["lm"] = lm, ms
        for name, base in (("d_raw", 0), ("d_sel", rec["c1"]["index"])):
            (corr, info), ms = timed(llm, lambda base=base: LC.conservative_correct(llm, hyps, base_index=base))
            rec[name] = {"base_index": base, "original": corr.original, "corrected": corr.corrected, "proposal": corr.proposal,
                         "changed": corr.changed, "accepted": corr.accepted, "reject_reason": corr.reject_reason,
                         "confirm": corr.confirm, "generated": info["generated"]}
            rec["timings_ms"][name] = ms
        outputs.append(rec)
        print(f"  {item['clip_id']:12} c1={rec['c1']['text']!r}  d_raw={rec['d_raw']['corrected']!r}"
              f"{' [proposal rejected: ' + rec['d_raw']['reject_reason'] + ']' if rec['d_raw']['reject_reason'] not in ('', 'ok', 'unchanged') else ''}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "llm_outputs.json").write_text(json.dumps({
        "model": LC.MODEL_NAME, "load_s": load_s, "gpu_mib_after_load": mem_loaded, "gpu_mib_peak_during_run": llm.memory_mib(),
        "lambdas": LAMBDAS, "gate": GATE, "outputs": outputs}, indent=1))
    print(f"wrote {out / 'llm_outputs.json'} (model load {load_s:.1f}s, GPU {mem_loaded['allocated']:.0f} MiB after load, "
          f"peak {llm.memory_mib()['peak']:.0f} MiB)")


# =====================================================================================
# analyze
# =====================================================================================
def polarity(text):
    return bool(LC.negation_words(LC.normalize_words(text)))


def fmt(x):
    return f"{x * 100:.1f}%"


def analyze(args):
    cache = json.loads(Path(args.cache).read_text())
    raw = json.loads((Path(args.dir) / "llm_outputs.json").read_text())
    clips = cache["clips"]
    assert all(c["split"] == "dev" for c in clips)
    by_id = {c["clip_id"]: c for c in clips}
    out_by_id = {o["clip_id"]: o for o in raw["outputs"]}
    phrase_set = X.norm_phrases(cache)
    subs = X.subsets(clips, phrase_set)
    silent, scored = subs["silent (17)"], subs["all scored (20)"]
    L = []
    emit = L.append

    A = {c["clip_id"]: c["nbest"][0]["text"] for c in clips}
    gate = {}
    for c in clips:
        text, accepted = RS.route(c["nbest"][0], c["phrases"], *GATE)
        gate[c["clip_id"]] = (text, accepted)
    B = {k: v[0] for k, v in gate.items()}
    methods = {"A raw": A, "B visual gate": B}
    confirm = {}  # method -> clip_id -> recommended?

    def add(name, fn, confirm_fn=None):
        methods[name] = {cid: fn(out_by_id[cid]) for cid in out_by_id}
        if confirm_fn:
            confirm[name] = {cid: confirm_fn(out_by_id[cid]) for cid in out_by_id}

    add("C1 LLM select", lambda o: o["c1"]["text"], lambda o: o["c1"]["confirm"])
    add("C1s LLM select + visual scores", lambda o: o["c1s"]["text"], lambda o: o["c1s"]["confirm"])
    add("C1x LLM select, order-averaged", lambda o: o["c1x"]["text"], lambda o: o["c1x"]["confirm"])

    def fusion_pick(o, lam):
        sums = [h["sum"] for h in o["candidates"]]
        return LC.fusion_choice(sums, o["lm_logprobs"], lam)

    for lam in LAMBDAS:
        def fn(o, lam=lam):
            return o["candidates"][fusion_pick(o, lam)[0]]["text"]

        def cf(o, lam=lam):
            best, fused = fusion_pick(o, lam)
            top2 = sorted(fused, reverse=True)[:2]
            return best != 0 or (len(top2) > 1 and top2[0] - top2[1] < FUSION_MARGIN)
        add(f"C2 LM fusion lam={lam}", fn, cf)
    add("C2 LM only", lambda o: o["candidates"][max(range(len(o["lm_logprobs"])), key=lambda i: o["lm_logprobs"][i])]["text"])
    add("D_raw LLM conservative", lambda o: o["d_raw"]["corrected"], lambda o: o["d_raw"]["confirm"])
    add("D_sel LLM conservative on C1 pick", lambda o: o["d_sel"]["corrected"], lambda o: o["d_sel"]["confirm"] or o["c1"]["confirm"])
    for name in [n for n in list(methods) if n.startswith(("C", "D"))]:
        short = {"C1 LLM select": "C1", "D_raw LLM conservative": "D_raw"}.get(name, name.split(" ")[0] + (" " + name.split(" ")[-1] if name.startswith("C2") else ""))
        ename = f"E B + {short}"
        methods[ename] = {cid: (gate[cid][0] if gate[cid][1] else methods[name][cid]) for cid in out_by_id}
        if name in confirm:
            confirm[ename] = {cid: (False if gate[cid][1] else confirm[name][cid]) for cid in out_by_id}

    # ---- headline table ------------------------------------------------------------------------
    emit("## 1. Method comparison (same dev recordings; silent = the 17 silent speech clips)\n")
    emit("Primary variants declared in advance: C1, D_raw, E = B + C1; the rest are ablations. Deltas are against A on the 17 silent clips "
         "(paired bootstrap 95% interval). 'wrong phrase' = a predefined phrase output for a different sentence.\n")
    emit("| method | silent WER | CER | exact | predefined (8) | unseen+contrast (9) | audible exact (3) | dWER vs A (95%) | better / worse | wrong phrase |\n|---|---|---|---|---|---|---|---|---|---|")
    metrics = {}
    for name, out in methods.items():
        r = X.eval_outputs(clips, out, phrase_set)
        metrics[name] = r
        d, ci, better, worse, _ = X.paired_delta(silent, out, A)
        emit(f"| {'**' + name + '**' if name in PRIMARY else name} | {fmt(r['silent (17)']['wer'])} | {fmt(r['silent (17)']['cer'])} | {r['silent (17)']['exact']}/17 | "
             f"{r['  silent predefined']['exact']}/8 | {r['  silent unseen+contrast']['exact']}/9 | {r['audible (3)']['exact']}/3 | "
             f"{d*100:+.1f} ({ci[0]*100:+.1f}, {ci[1]*100:+.1f}) | {better} / {worse} | {len(r['wrong_phrase'])} |")
    emit("")

    # ---- per clip: changes vs raw ---------------------------------------------------------------------
    emit("## 2. What each primary method changed relative to raw (all dev clips)\n")
    # the three C2 tables were added after seeing section 1, to check what the fusion gain is made of
    for name in ("B visual gate", "C1 LLM select", "D_raw LLM conservative", "E B + C1",
                 "C2 LM fusion lam=0.25", "C2 LM fusion lam=0.5", "C2 LM fusion lam=1.0"):
        emit(f"**{name}**\n")
        emit("| clip | truth | raw | new output | word errors raw -> new | verdict |\n|---|---|---|---|---|---|")
        any_change = False
        for c in clips:
            cid = c["clip_id"]
            if M.normalize_text(methods[name][cid]) == M.normalize_text(A[cid]):
                continue
            any_change = True
            if c["no_speech"]:
                emit(f"| {cid} | (no speech) | {A[cid][:30]} | {methods[name][cid][:30]} | - | no-speech clip |")
                continue
            e0, e1 = X.clip_errors(c, A[cid]), X.clip_errors(c, methods[name][cid])
            emit(f"| {cid} | {c['text']} | {A[cid]} | {methods[name][cid]} | {e0} -> {e1} | {'IMPROVED' if e1 < e0 else 'WORSE' if e1 > e0 else 'same errors'} |")
        if not any_change:
            emit("| (no clip changed) | | | | | |")
        emit("")

    # ---- meaning-changing errors ------------------------------------------------------------------
    emit("## 3. Negation and meaning-changing errors\n")
    emit("Automatic checks on the 20 scored clips: 'polarity flip' = the output has a negation word and the truth does not, or the reverse; "
         "'number' = number words/digits differ; 'partner' = the output is the other sentence of its contrast pair. "
         "Meaning-changing errors the checks cannot see (e.g. on/off) are listed by hand below.\n")
    emit("| method | polarity flips | number mismatches | partner-sentence outputs | clips with a polarity flip |\n|---|---|---|---|---|")
    partner = {c["clip_id"]: next((o["text"] for o in clips if o["pair_id"] == c["pair_id"] and o is not c and o["set"] == "contrast"), None)
               for c in clips if c["set"] == "contrast"}
    for name, out in methods.items():
        flips = [c["clip_id"] for c in scored if polarity(out[c["clip_id"]]) != polarity(c["text"])]
        nums = [c["clip_id"] for c in scored if LC.number_words(LC.normalize_words(out[c["clip_id"]])) != LC.number_words(LC.normalize_words(c["text"]))]
        part = [cid for cid, ptext in partner.items() if ptext and M.normalize_text(out[cid]) == M.normalize_text(ptext)]
        emit(f"| {name} | {len(flips)} | {len(nums)} | {len(part)} | {', '.join(flips) or '-'} |")
    emit("")
    emit("Raw outputs of the contrast clips for reference (truth -> raw):\n")
    for c in clips:
        if c["set"] == "contrast":
            emit(f"- {c['clip_id']}: '{c['text']}' -> '{A[c['clip_id']]}'")
    emit("")

    # ---- confirmation recommendations ---------------------------------------------------------------
    emit("## 4. Is the 'confirm' recommendation useful? (scored clips, n=20)\n")
    emit("For each method that recommends confirmation: how many outputs are wrong (not exactly the truth), how many of those were flagged "
         "(recall), and how many flagged outputs were in fact wrong (precision). All thresholds are declared rules, not tuned; LLM probabilities are uncalibrated.\n")
    emit("| method | flagged | wrong outputs | wrong & flagged (recall) | flagged & wrong (precision) | correct outputs flagged |\n|---|---|---|---|---|---|")
    for name, flags in confirm.items():
        wrong = [c for c in scored if methods[name][c["clip_id"]] and M.clip_metrics(c["text"], methods[name][c["clip_id"]])["exact"] == 0]
        flagged = [c for c in scored if flags[c["clip_id"]]]
        both = [c for c in wrong if flags[c["clip_id"]]]
        right_flagged = [c for c in flagged if c not in wrong]
        emit(f"| {name} | {len(flagged)} | {len(wrong)} | {len(both)}/{len(wrong)} | {len(both)}/{len(flagged) or 1} | {len(right_flagged)} |")
    ref = [c for c in scored if c["nbest"] and RS.score(c["nbest"][0], 0.1, "tok") < -0.30]
    ref_wrong = [c for c in scored if M.clip_metrics(c["text"], A[c["clip_id"]])["exact"] == 0]
    emit(f"| (reference) raw output flagged when visual score per token < -0.30 (a Phase-1 dev observation, so optimistic) | {len(ref)} | {len(ref_wrong)} | "
         f"{len([c for c in ref_wrong if c in ref])}/{len(ref_wrong)} | {len([c for c in ref if c in ref_wrong])}/{len(ref) or 1} | {len([c for c in ref if c not in ref_wrong])} |")
    emit("")

    # ---- D details --------------------------------------------------------------------------------------
    emit("## 5. Conservative correction: what the LLM proposed and what the guards did\n")
    emit("| clip | truth | original | LLM proposal | guard | final |\n|---|---|---|---|---|---|")
    for o in raw["outputs"]:
        d = o["d_raw"]
        if not d["proposal"] or M.normalize_text(d["proposal"]) == M.normalize_text(d["original"]):
            continue
        c = by_id[o["clip_id"]]
        emit(f"| {o['clip_id']} | {c['text'] or '(no speech)'} | {d['original'][:34]} | {d['proposal'][:34]} | {d['reject_reason'] if not d['accepted'] else 'accepted'} | {d['corrected'][:34]} |")
    n_prop = sum(1 for o in raw["outputs"] if o["d_raw"]["proposal"] and M.normalize_text(o["d_raw"]["proposal"]) != M.normalize_text(o["d_raw"]["original"]))
    n_acc = sum(o["d_raw"]["accepted"] and o["d_raw"]["changed"] for o in raw["outputs"])
    emit(f"\nD_raw: the LLM proposed a different sentence in {n_prop} of {len(raw['outputs'])} clips; the guards accepted {n_acc}. "
         f"Rejection reasons: { {r: [o['d_raw']['reject_reason'] for o in raw['outputs']].count(r) for r in sorted({o['d_raw']['reject_reason'] for o in raw['outputs']} - {'ok', 'unchanged', ''})} }.\n")

    # ---- how the letter-probability behaves ------------------------------------------------------------
    emit("## 6. Multiple-choice behaviour (C1)\n")
    emit("| clip | candidates | LLM picked | top option probability (uncalibrated) | letter mass | visual top-1 | picked == visual top-1 |\n|---|---|---|---|---|---|---|")
    for o in raw["outputs"]:
        c1 = o["c1"]
        emit(f"| {o['clip_id']} | {c1['n_candidates']} | {'ABCDEFGHIJ'[c1['index']]} | {max(c1['option_probs']):.2f} | {c1['letter_mass']:.2f} | {o['candidates'][0]['text'][:30]} | {c1['index'] == 0} |")
    emit("")
    picks = [o["c1"]["index"] for o in raw["outputs"]]
    emit(f"C1 picked the visual top-1 (A) in {picks.count(0)} of {len(picks)} clips; position of the picks: {sorted(picks)}.\n")

    # ---- cost -------------------------------------------------------------------------------------------
    emit("## 7. Latency and memory\n")
    emit(f"Model: `{raw['model']}` (bf16, local cache, no network). Load time {raw['load_s']:.1f} s. GPU memory after loading: "
         f"{raw['gpu_mib_after_load']['allocated']:.0f} MiB allocated; peak during the run {raw['gpu_mib_peak_during_run']['peak']:.0f} MiB. "
         f"(The Auto-AVSR process measured separately at about 1.9 GB in nvidia-smi, so both fit together easily on this machine.)\n")
    emit("| step (per clip, 22 clips) | mean ms | median | p95 | max |\n|---|---|---|---|---|")
    names = {"c1": "C1 multiple choice", "c1s": "C1s (with scores)", "c1x": "C1x (two orders)", "lm": "LM log-probs of 10 candidates (C2)", "d_raw": "D_raw generate + guards", "d_sel": "D_sel generate + guards"}
    for k, label in names.items():
        v = sorted(o["timings_ms"][k] for o in raw["outputs"])
        emit(f"| {label} | {st.mean(v):.0f} | {st.median(v):.0f} | {v[int(0.95 * (len(v) - 1))]:.0f} | {v[-1]:.0f} |")
    base = [c["total_ms"] for c in clips]
    emit(f"\nFor scale: baseline lip reading (video -> raw text) took {st.mean(base):.0f} ms mean per clip.\n")

    out_dir = Path(args.dir)
    (out_dir / "report.md").write_text("\n".join(L) + "\n")
    import csv
    with open(out_dir / "per_clip_methods.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip_id", "set", "speech_mode", "truth"] + list(methods))
        for c in clips:
            w.writerow([c["clip_id"], c["set"], c["speech_mode"], c["text"]] + [methods[m][c["clip_id"]] for m in methods])
    print("\n".join(L))
    print(f"\nwrote {out_dir / 'report.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("cache")
    r.add_argument("--out", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("cache")
    a.add_argument("dir")
    args = ap.parse_args()
    run(args) if args.cmd == "run" else analyze(args)


if __name__ == "__main__":
    main()
