"""Phase 1 experiment: model-based rescoring of lip-reading output, on the DEVELOPMENT split only.

    python eval/rescoring_experiment.py collect MANIFEST --out DIR [--baseline RESULTS_DIR]
    python eval/rescoring_experiment.py analyze DIR

collect (needs the GPU venv): runs every dev clip once, keeps the encoder output, and caches
    the 10-best list, the scores of the 8 predefined phrases (timed) and of the ground-truth
    sentence. Test-split rows are refused before the model is even loaded.
analyze (pure python): compares, on the same recordings,
    A  raw Auto-AVSR decoding
    B  the existing fuzzy matcher (correction.correct, threshold 70)
    C  visual likelihood scoring of the 8 phrases, with gates that decide when to use a phrase
    R  open-vocabulary re-ranking of the 10-best with other decoder/CTC weights and normalisation
All variants and grids are declared below before any result is looked at, and every cell is
reported, not just the best. Anything chosen on dev is also reported leave-one-clip-out.
"""

import argparse
import csv
import json
import math
import os
import random
import statistics as st
import sys
import time
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # before torch, see lipreading.py

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import rescoring as RS  # noqa: E402
import vsr_metrics as M  # noqa: E402

PHRASES_FILE = ROOT / "backend" / "demo_phrases.txt"

# ---- declared before looking at results -------------------------------------------------
RERANK_W = (0.0, 0.1, 0.3, 0.5, 1.0)  # CTC weight: 0 = decoder only, 0.1 = beam baseline, 1 = CTC only
RERANK_NORMS = ("sum", "tok", "sqrt")
GATES = {  # feature -> thresholds, most conservative (accepts fewest) first
    "gap_sum": [0, 1, 2, 3, 4, 6, 8, 10, 15, 20, 30, 50],      # nats worse than the free decode
    "gap_tok": [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5],  # nats per token
    "margin_sum": [12, 8, 5, 3, 2, 1, 0],                         # best phrase vs runner-up
    "margin_tok": [1.5, 1.0, 0.5, 0.3, 0.2, 0.1, 0.0],
}
NO_SPEECH_PENALTY = 4  # word errors charged when a no-speech clip is turned into a phrase (LOO objective)


# ======================================================================================
# collect
# ======================================================================================
def collect(args):
    phrases = [p.strip() for p in PHRASES_FILE.read_text().splitlines() if p.strip()]
    rows, _ = M.load_manifest(args.manifest, phrases)
    if not any(r.get("split") for r in rows):
        sys.exit("manifest has no split column: refusing to run an experiment without a dev/test split")
    rows = [r for r in rows if r["split"] == "dev"]  # test rows are dropped here, before the model loads
    assert rows and all(r["split"] == "dev" for r in rows)
    print(f"{len(rows)} dev clips (test split excluded)")

    import torch  # noqa: E402
    import lipreading as L  # noqa: E402

    baseline = {}
    if args.baseline:
        for line in open(Path(args.baseline) / "predictions.jsonl"):
            d = json.loads(line)
            baseline[d["clip_id"]] = d["raw_text"]
    for _ in range(2):  # warm the phrase-scoring path too
        L.score_candidates(L.lip_read_detailed(rows[0]["video_path"]), phrases)

    clips, mismatches = [], []
    for r in rows:
        res = L.lip_read_detailed(r["video_path"])
        clip = {k: r.get(k, "") for k in ("clip_id", "set", "split", "speech_mode", "pair_id", "text", "category")}
        clip.update({"no_speech": r["no_speech"], "labeled": r["labeled"], "reason": res.reason, "error": res.error,
                     "total_ms": res.timings_ms.get("total_ms"), "duration_s": res.frames.duration_s,
                     "nbest": [], "phrases": [], "truth": None})
        if res.encoder_out is not None:
            clip["nbest"] = [{"text": h.text, "token_ids": h.token_ids, "dec": h.decoder_logprob, "ctc": h.ctc_logprob,
                              "n_tok": h.n_scored_tokens} for h in res.nbest]
            t = time.perf_counter()
            scored = L.score_candidates(res, phrases)
            torch.cuda.synchronize()
            clip["phrase_ms"] = (time.perf_counter() - t) * 1000
            clip["phrases"] = [{"text": p, "dec": s.decoder_logprob, "ctc": s.ctc_logprob, "n_tok": s.n_scored_tokens,
                                "unk": s.unk_count} for p, s in zip(phrases, scored)]
            if r["text"]:  # dev ground truth, used only for the model-vs-search diagnostic
                s = L.score_candidates(res, [r["text"]])[0]
                clip["truth"] = {"text": r["text"], "dec": s.decoder_logprob, "ctc": s.ctc_logprob, "n_tok": s.n_scored_tokens,
                                 "unk": s.unk_count}
        if baseline and baseline.get(clip["clip_id"]) != res.raw_text:
            mismatches.append((clip["clip_id"], baseline.get(clip["clip_id"]), res.raw_text))
        clips.append(clip)
        print(f"  {clip['clip_id']:12} raw={res.raw_text!r}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "cache.json").write_text(json.dumps({
        "phrases": phrases, "beam_size": L.BEAM_SIZE, "clips": clips,
        "baseline_check": {"compared": bool(baseline), "mismatches": mismatches}}, indent=1))
    print(f"wrote {out / 'cache.json'}; raw predictions identical to the earlier baseline run: "
          f"{'n/a' if not baseline else not mismatches}")


# ======================================================================================
# analysis helpers
# ======================================================================================
def norm_phrases(cache):
    return {M.normalize_text(p) for p in cache["phrases"]}


def free_of(clip):
    return clip["nbest"][0] if clip["nbest"] else None


def subsets(clips, phrase_set):
    scored = [c for c in clips if c["labeled"] and not c["no_speech"]]
    silent = [c for c in scored if c["speech_mode"] == "silent"]
    is_phrase = lambda c: M.normalize_text(c["text"]) in phrase_set
    return {
        "silent (17)": silent,
        "  silent predefined": [c for c in silent if c["set"] == "predefined"],
        "  silent unseen+contrast": [c for c in silent if c["set"] in ("unseen", "contrast")],
        "  silent unseen only": [c for c in silent if c["set"] == "unseen"],
        "audible (3)": [c for c in scored if c["speech_mode"] == "audible"],
        "all scored (20)": scored,
        "predefined, any mode (10)": [c for c in scored if is_phrase(c)],
        "not predefined, any mode (10)": [c for c in scored if not is_phrase(c)],
    }


def eval_outputs(clips, outputs, phrase_set):
    """Metrics of one method. outputs: clip_id -> text."""
    res = {}
    for name, group in subsets(clips, phrase_set).items():
        ms = [M.clip_metrics(c["text"], outputs[c["clip_id"]]) for c in group]
        words = sum(m["ref_words"] for m in ms)
        res[name] = {"n": len(group), "wer": sum(m["word_errors"] for m in ms) / words,
                     "cer": sum(m["char_errors"] for m in ms) / sum(m["ref_chars"] for m in ms),
                     "exact": sum(m["exact"] for m in ms), "errors": sum(m["word_errors"] for m in ms)}
    wrong, quiet = [], []
    for c in clips:
        out = M.normalize_text(outputs[c["clip_id"]])
        if out in phrase_set and out != M.normalize_text(c["text"]):
            (quiet if c["no_speech"] else wrong).append(c["clip_id"])
    res["wrong_phrase"] = wrong      # a predefined phrase spoken in place of the real sentence
    res["phrase_on_no_speech"] = quiet
    return res


def clip_errors(c, text):
    return M.clip_metrics(c["text"], text)["word_errors"]


def paired_delta(clips_subset, outputs, base_outputs, seed=0):
    """Change in WER vs the baseline on the same clips: (delta, bootstrap 95% CI, improved, regressed, same)."""
    e = [(clip_errors(c, outputs[c["clip_id"]]), clip_errors(c, base_outputs[c["clip_id"]]),
          M.clip_metrics(c["text"], "")["ref_words"]) for c in clips_subset]
    words = sum(x[2] for x in e)
    delta = (sum(x[0] for x in e) - sum(x[1] for x in e)) / words
    rng = random.Random(seed)
    boots = []
    for _ in range(4000):
        s = [rng.choice(e) for _ in e]
        boots.append((sum(x[0] for x in s) - sum(x[1] for x in s)) / max(1, sum(x[2] for x in s)))
    boots.sort()
    better = sum(x[0] < x[1] for x in e)
    worse = sum(x[0] > x[1] for x in e)
    return delta, (boots[100], boots[3899]), better, worse, len(e) - better - worse


def loo(clips, grid, output_fn, phrase_set):
    """Leave-one-clip-out: for each clip pick the grid value that minimises word errors on the
    other clips (no-speech clips turned into a phrase cost NO_SPEECH_PENALTY), apply it to the
    held-out clip. Ties go to the first grid value (grids list the most conservative first)."""
    def cost(c, value):
        text = output_fn(c, value)
        if c["no_speech"]:
            return NO_SPEECH_PENALTY if M.normalize_text(text) in phrase_set else 0
        return clip_errors(c, text) if c["labeled"] else 0
    table = {(c["clip_id"], v): cost(c, v) for c in clips for v in grid}
    outputs, chosen = {}, {}
    for c in clips:
        best = min(grid, key=lambda v: (sum(table[(o["clip_id"], v)] for o in clips if o is not c), grid.index(v)))
        outputs[c["clip_id"]], chosen[c["clip_id"]] = output_fn(c, best), best
    return outputs, chosen


# ======================================================================================
# analyze
# ======================================================================================
def fmt(x, pct=True):
    return f"{x * 100:.1f}%" if pct else f"{x:.3f}"


def analyze(args):
    from rapidfuzz import fuzz, process, utils  # same scorer as backend/correction.py

    cache = json.loads((Path(args.dir) / "cache.json").read_text())
    clips, phrases = cache["clips"], cache["phrases"]
    assert all(c["split"] == "dev" for c in clips)
    phrase_set = norm_phrases(cache)
    ok = [c for c in clips if c["nbest"]]
    assert len(ok) == len(clips), "a dev clip failed to produce hypotheses"
    scored = [c for c in clips if c["labeled"] and not c["no_speech"]]
    silent = subsets(clips, phrase_set)["silent (17)"]
    lines = []
    emit = lines.append
    results = {}

    # ---- A, B ------------------------------------------------------------------
    A = {c["clip_id"]: free_of(c)["text"] for c in clips}
    from correction import correct
    B = {c["clip_id"]: correct(A[c["clip_id"]], []) for c in clips}
    results["A raw"], results["B fuzzy(70)"] = A, B

    # ---- closed-set identification (oracle routing: only clips whose truth is a phrase) ------
    positives = [c for c in clips if c["labeled"] and M.normalize_text(c["text"]) in phrase_set]
    negatives = [c for c in clips if c not in positives]
    ident = {}
    for w in RERANK_W:
        for norm in RERANK_NORMS:
            hits, ranks = 0, []
            for c in positives:
                order = [p["text"] for p in RS.ranked(c["phrases"], w, norm)]
                rank = [M.normalize_text(t) for t in order].index(M.normalize_text(c["text"])) + 1
                ranks.append(rank)
                hits += rank == 1
            ident[(w, norm)] = (hits, ranks)
    fuzzy_hits = 0
    fuzzy_ranks = []
    for c in positives:
        order = [m[0] for m in process.extract(A[c["clip_id"]], phrases, scorer=fuzz.ratio, processor=utils.default_process, limit=8)]
        r = [M.normalize_text(t) for t in order].index(M.normalize_text(c["text"])) + 1
        fuzzy_ranks.append(r)
        fuzzy_hits += r == 1
    emit("## 1. Closed-set phrase identification (clips whose truth IS one of the 8 phrases)\n")
    emit(f"{len(positives)} clips ({sum(c['speech_mode']=='silent' for c in positives)} silent, "
         f"{sum(c['speech_mode']=='audible' for c in positives)} audible). Question: if we knew the clip is a predefined phrase, "
         "which method picks the right one of the 8? Raw decoding is not a closed-set method, so its row is how often the raw text "
         "is already exactly the phrase.\n")
    emit("| method | top-1 correct | truth ranked (per clip, in clip order) |\n|---|---|---|")
    emit(f"| A raw decode == phrase | {sum(M.normalize_text(A[c['clip_id']]) == M.normalize_text(c['text']) for c in positives)}/{len(positives)} | n/a |")
    emit(f"| B fuzzy argmax (ignoring its threshold) | {fuzzy_hits}/{len(positives)} | {fuzzy_ranks} |")
    for (w, norm), (hits, ranks) in ident.items():
        label = {0.0: "decoder only", 0.1: "beam weights", 1.0: "CTC only"}.get(w, f"w_ctc={w}")
        emit(f"| C visual, {label}, {norm} | {hits}/{len(positives)} | {ranks} |")
    emit("")
    emit("Clip order: " + ", ".join(c["clip_id"] for c in positives) + "\n")

    # ---- routing features ------------------------------------------------------------
    feats = {c["clip_id"]: RS.routing_features(free_of(c), c["phrases"]) for c in clips}
    emit("## 2. Routing: can a score tell 'predefined phrase' from 'unseen sentence / no speech'?\n")
    emit(f"Positives (truth is a phrase): {len(positives)} clips. Negatives (unseen, contrast, audible-unseen, no-speech): {len(negatives)} clips. "
         "AUROC = probability that a random positive looks more phrase-like than a random negative (0.5 = no information).\n")
    emit("| feature (phrase-like direction) | AUROC | positives range | negatives range |\n|---|---|---|---|")
    for f, sign in (("gap_sum", -1), ("gap_tok", -1), ("margin_sum", 1), ("margin_tok", 1)):
        pv = [sign * feats[c["clip_id"]][f] for c in positives]
        nv = [sign * feats[c["clip_id"]][f] for c in negatives]
        emit(f"| {f} ({'lower' if sign < 0 else 'higher'} = phrase) | {fmt(RS.auroc(pv, nv), False)} | "
             f"{min(sign*v for v in pv):.2f} to {max(sign*v for v in pv):.2f} | {min(sign*v for v in nv):.2f} to {max(sign*v for v in nv):.2f} |")
    emit("")
    emit("Per-clip routing features (gap_sum = free-decode score minus best-phrase score, in nats; margin_sum = best phrase minus runner-up):\n")
    emit("| clip | truth is phrase | free decode | best phrase | gap_sum | gap_tok | margin_sum |\n|---|---|---|---|---|---|---|")
    for c in sorted(clips, key=lambda c: (c["clip_id"] not in {p["clip_id"] for p in positives}, feats[c["clip_id"]]["gap_sum"])):
        f = feats[c["clip_id"]]
        emit(f"| {c['clip_id']} | {'yes' if c in positives else 'no'} | {A[c['clip_id']][:34]} | {f['phrase']} | "
             f"{f['gap_sum']:.1f} | {f['gap_tok']:.2f} | {f['margin_sum']:.1f} |")
    emit("")

    # ---- gates sweep ---------------------------------------------------------------------
    def gate_out(c, thr, feature):
        return RS.route(free_of(c), c["phrases"], feature, thr)[0]
    emit("## 3. Gated hybrid (phrase if the gate accepts, else the raw open-vocabulary text)\n")
    emit("Every threshold in the declared grid. 'wrong phrase' = a predefined phrase output for a clip whose truth is a different sentence; "
         "'phrase on no-speech' = a phrase output for a clip where nothing was said. Silent WER baseline (A): "
         f"{fmt(eval_outputs(clips, A, phrase_set)['silent (17)']['wer'])}.\n")
    emit("| feature | threshold | silent WER | silent exact | predefined exact (10) | not-predefined exact (10) | wrong phrase | phrase on no-speech |\n|---|---|---|---|---|---|---|---|")
    sweeps = {}
    for feature, grid in GATES.items():
        for thr in grid:
            out = {c["clip_id"]: gate_out(c, thr, feature) for c in clips}
            r = eval_outputs(clips, out, phrase_set)
            sweeps[(feature, thr)] = (out, r)
            emit(f"| {feature} | {thr} | {fmt(r['silent (17)']['wer'])} | {r['silent (17)']['exact']}/17 | "
                 f"{r['predefined, any mode (10)']['exact']}/10 | {r['not predefined, any mode (10)']['exact']}/10 | "
                 f"{len(r['wrong_phrase'])} | {len(r['phrase_on_no_speech'])} |")
    forced = {c["clip_id"]: feats[c["clip_id"]]["phrase"] for c in clips}
    rf = eval_outputs(clips, forced, phrase_set)
    emit(f"| (forced: every clip -> best phrase) | inf | {fmt(rf['silent (17)']['wer'])} | {rf['silent (17)']['exact']}/17 | "
         f"{rf['predefined, any mode (10)']['exact']}/10 | {rf['not predefined, any mode (10)']['exact']}/10 | {len(rf['wrong_phrase'])} | {len(rf['phrase_on_no_speech'])} |")
    emit("")
    results["C forced (diagnostic only)"] = forced

    # Operating point by a rule fixed in advance for gap_sum: 'the most permissive threshold in the declared grid with
    # no wrong phrase and no phrase on a no-speech clip'. gap_sum has no such threshold (see the table), so the SAME
    # rule is applied to the other three features afterwards: that extension is post hoc, made after seeing gap_sum fail.
    emit("Operating points. Rule: the most permissive threshold in the grid with zero wrong phrases and zero phrases on no-speech clips "
         "(declared for gap_sum before looking; applied to the other features after gap_sum turned out to have none, i.e. post hoc). "
         "Leave-one-clip-out (LOO) picks the threshold on the other 21 clips and applies it to the held-out clip.\n")
    emit("| feature | dev-safe threshold | LOO thresholds chosen (value: times) |\n|---|---|---|")
    op_points = {}
    for feature, grid in GATES.items():
        safe = [t for t in grid if not sweeps[(feature, t)][1]["wrong_phrase"] and not sweeps[(feature, t)][1]["phrase_on_no_speech"]]
        permissive = (max if feature.startswith("gap") else min)(safe) if safe else None
        loo_out, chosen = loo(clips, grid, lambda c, t, f=feature: gate_out(c, t, f), phrase_set)
        op_points[feature] = permissive
        if permissive is not None:
            results[f"C gate {feature} (dev-safe point {permissive})"] = sweeps[(feature, permissive)][0]
        results[f"C gate {feature} (leave-one-out)"] = loo_out
        emit(f"| {feature} | {permissive if permissive is not None else 'none exists'} | { {k: list(chosen.values()).count(k) for k in sorted(set(chosen.values()))} } |")
    emit("")

    # ---- reranking grid ---------------------------------------------------------------
    emit("## 4. Open-vocabulary re-ranking of the 10-best\n")
    emit("Baseline cell (w_ctc=0.1, sum) is the beam's own order, so it reproduces A exactly. Silent clips only (17); oracle top-10 WER "
         f"{fmt(sum(min(clip_errors(c, h['text']) for h in c['nbest']) for c in silent) / sum(M.clip_metrics(c['text'], '')['ref_words'] for c in silent))}.\n")
    emit("| w_ctc | norm | silent WER | silent CER | silent exact | improved | regressed | dWER vs A (95% bootstrap) |\n|---|---|---|---|---|---|---|---|")
    rerank_out = {}
    for w in RERANK_W:
        for norm in RERANK_NORMS:
            out = {c["clip_id"]: RS.rerank(c["nbest"], w, norm)["text"] for c in clips}
            rerank_out[(w, norm)] = out
            r = eval_outputs(clips, out, phrase_set)["silent (17)"]
            d, ci, better, worse, same = paired_delta(silent, out, A)
            tag = " (baseline)" if (w, norm) == (0.1, "sum") else ""
            emit(f"| {w}{tag} | {norm} | {fmt(r['wer'])} | {fmt(r['cer'])} | {r['exact']}/17 | {better} | {worse} | {d*100:+.1f} pts ({ci[0]*100:+.1f}, {ci[1]*100:+.1f}) |")
    assert rerank_out[(0.1, "sum")] == A, "baseline rerank must reproduce the beam's choice"
    emit("")
    grid_cells = [(w, n) for w in RERANK_W for n in RERANK_NORMS]
    rr_loo, rr_chosen = loo(clips, grid_cells, lambda c, cell: rerank_out[cell][c["clip_id"]], phrase_set)
    results["R rerank (leave-one-out over the grid)"] = rr_loo
    best_cell = min(grid_cells, key=lambda cell: (eval_outputs(clips, rerank_out[cell], phrase_set)["silent (17)"]["errors"], grid_cells.index(cell)))
    results[f"R rerank best-on-dev {best_cell} (optimistic)"] = rerank_out[best_cell]
    results["R rerank per-token (0.1, tok)"] = rerank_out[(0.1, "tok")]
    emit(f"Best cell on dev: {best_cell} (selected on the same 17 clips it is scored on, so optimistic). Leave-one-out choices: "
         f"{ {str(k): list(rr_chosen.values()).count(k) for k in sorted(set(rr_chosen.values()))} }.\n")

    # ---- model vs search diagnostic --------------------------------------------------------
    emit("## 5. Does the model itself prefer the truth? (silent + audible scored clips)\n")
    d = [(c["clip_id"], RS.score(c["truth"], 0.1, "sum") - RS.score(free_of(c), 0.1, "sum"), c["truth"]["unk"]) for c in scored]
    emit("Truth score minus free-decode score under the beam's own formula (nats; positive = the model rates the TRUTH higher than "
         "its own best hypothesis, i.e. beam search missed it; negative = the model itself prefers the wrong text).\n")
    emit("| clip | truth - free (nats) | unk tokens in truth |\n|---|---|---|")
    for cid, diff, unk in sorted(d, key=lambda x: -x[1]):
        emit(f"| {cid} | {diff:+.1f} | {unk} |")
    emit(f"\nTruth scores higher than the free decode in {sum(x[1] > 0 for x in d)} of {len(d)} clips.\n")

    # ---- main comparison -----------------------------------------------------------------
    emit("## 6. Method comparison on the same dev recordings\n")
    emit("Baseline for every delta is A (raw). 'wrong phrase' counts clips where a predefined phrase is output but the truth is another sentence "
         "(raw decoding can do this by accident); 'phrase on no-speech' counts no-speech clips turned into a phrase.\n")
    emit("| method | silent WER | silent CER | silent exact | silent predefined exact (8) | silent unseen+contrast exact (9) | audible exact (3) | wrong phrase | phrase on no-speech | improved / regressed / same (silent) |\n|---|---|---|---|---|---|---|---|---|---|")
    summary_rows = {}
    for name, out in results.items():
        r = eval_outputs(clips, out, phrase_set)
        d, ci, better, worse, same = paired_delta(silent, out, A)
        summary_rows[name] = r
        emit(f"| {name} | {fmt(r['silent (17)']['wer'])} | {fmt(r['silent (17)']['cer'])} | {r['silent (17)']['exact']}/17 | "
             f"{r['  silent predefined']['exact']}/8 | {r['  silent unseen+contrast']['exact']}/9 | {r['audible (3)']['exact']}/3 | "
             f"{len(r['wrong_phrase'])} | {len(r['phrase_on_no_speech'])} | {better} / {worse} / {same} |")
    emit("")

    # ---- per-clip table ---------------------------------------------------------------------
    key_methods = ["A raw", "B fuzzy(70)", f"C gate gap_tok (dev-safe point {op_points['gap_tok']})", "C gate gap_tok (leave-one-out)",
                   "R rerank (leave-one-out over the grid)"]
    emit("## 7. Per-clip outputs (only clips where some method differs from A are marked)\n")
    emit("| clip | truth | " + " | ".join(m.split(" (")[0] if m.startswith("R") or m.startswith("C") else m for m in key_methods) + " |\n|---|---|" + "---|" * len(key_methods))
    for c in clips:
        outs = [results[m][c["clip_id"]] for m in key_methods]
        marks = []
        for m, o in zip(key_methods, outs):
            if m == "A raw" or c["no_speech"] or not c["labeled"]:
                marks.append(o[:40])
                continue
            e, e0 = clip_errors(c, o), clip_errors(c, A[c["clip_id"]])
            marks.append(f"{o[:40]} {'(better)' if e < e0 else '(WORSE)' if e > e0 else ''}".strip())
        emit(f"| {c['clip_id']} | {c['text'] or '(no speech)'} | " + " | ".join(marks) + " |")
    emit("")

    # ---- runtime ----------------------------------------------------------------------------
    t = [c["phrase_ms"] for c in clips if "phrase_ms" in c]
    base_total = [c["total_ms"] for c in clips]
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        for c in clips:
            RS.rerank(c["nbest"], 0.3, "tok")
    rr_us = (time.perf_counter() - t0) / (n * len(clips)) * 1e6
    t0 = time.perf_counter()
    for _ in range(n):
        for c in clips:
            RS.route(free_of(c), c["phrases"], "gap_sum", 10)
    gate_us = (time.perf_counter() - t0) / (n * len(clips)) * 1e6
    emit("## 8. Runtime overhead\n")
    emit(f"- Baseline `lip_read_detailed` per clip: mean {st.mean(base_total):.0f} ms (median {st.median(base_total):.0f}).")
    emit(f"- Scoring the 8 phrases (one batched decoder pass + CTC, encoder output reused): mean {st.mean(t):.0f} ms, median {st.median(t):.0f}, max {max(t):.0f}.")
    emit(f"- Re-ranking the 10-best (pure arithmetic on cached scores): about {rr_us:.0f} microseconds. Gate decision: about {gate_us:.0f} microseconds.\n")

    # ---- extra checks ---------------------------------------------------------------------
    emit("## 9. Extra checks\n")
    emit("**C versus the existing fuzzy matcher (B), paired on the 17 silent clips** (negative dWER = C better than B):\n")
    emit("| C variant | dWER vs B (95% bootstrap) | better / worse / same clips | audible exact (C vs B) |\n|---|---|---|---|")
    for name in results:
        if name.startswith("C gate") :
            d, ci, better, worse, same = paired_delta(silent, results[name], B)
            r = summary_rows[name]
            emit(f"| {name} | {d*100:+.1f} pts ({ci[0]*100:+.1f}, {ci[1]*100:+.1f}) | {better} / {worse} / {same} | {r['audible (3)']['exact']}/3 vs {summary_rows['B fuzzy(70)']['audible (3)']['exact']}/3 |")
    emit("")
    emit("**Clips each gate changes relative to raw (silent and audible):**\n")
    for name in results:
        if name.startswith("C gate") and "dev-safe" in name:
            changed = [(c["clip_id"], A[c["clip_id"]], results[name][c["clip_id"]]) for c in clips if results[name][c["clip_id"]] != A[c["clip_id"]]]
            emit(f"- {name}: " + "; ".join(f"{cid}: '{a}' -> '{b}'" for cid, a, b in changed))
    emit("")
    quiet = [c for c in clips if c["no_speech"]]
    speech = [c for c in clips if not c["no_speech"]]
    emit("**Can anything flag the no-speech clips?** (positives = no-speech, 2 clips, so treat as anecdote; the clip duration is a "
         "recording artefact here: the no-speech clips were recorded 6.0 s and 9.2 s long, speech clips 2.5-4.3 s)\n")
    emit("| signal | AUROC (no-speech detected) | no-speech values | speech range |\n|---|---|---|---|")
    for label, fn in (("free-decode score per token (lower = no-speech)", lambda c: -RS.score(free_of(c), 0.1, "tok")),
                      ("free-decode n-best margin (higher = no-speech)", lambda c: RS.score(c["nbest"][0]) - RS.score(c["nbest"][1])),
                      ("clip duration, s (artefact)", lambda c: c["duration_s"])):
        qv, sv = [fn(c) for c in quiet], [fn(c) for c in speech]
        emit(f"| {label} | {fmt(RS.auroc(qv, sv), False)} | {', '.join(f'{v:.2f}' for v in qv)} | {min(sv):.2f} to {max(sv):.2f} |")
    emit("")

    out_dir = Path(args.dir)
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    with open(out_dir / "per_clip_methods.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["clip_id", "set", "speech_mode", "truth"] + list(results))
        for c in clips:
            w.writerow([c["clip_id"], c["set"], c["speech_mode"], c["text"]] + [results[m][c["clip_id"]] for m in results])
    print("\n".join(lines))
    print(f"\nwrote {out_dir / 'report.md'} and per_clip_methods.csv")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("manifest")
    c.add_argument("--out", required=True)
    c.add_argument("--baseline", help="earlier evaluate.py results dir, to check the raw predictions are unchanged")
    a = sub.add_parser("analyze")
    a.add_argument("dir")
    args = ap.parse_args()
    collect(args) if args.cmd == "collect" else analyze(args)


if __name__ == "__main__":
    main()
