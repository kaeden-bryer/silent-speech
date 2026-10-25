"""Silent-speech recognition pipeline (all local, on this GPU):

    video -> Auto-AVSR (10-best) -> visual phrase gate -> Qwen likelihood fusion -> final text

    from pipeline import get_pipeline
    result = get_pipeline().recognize(video_path)

result = {
    "raw_text":           Auto-AVSR's own best guess, untouched,
    "final_text":         the pipeline's pick: ALWAYS one of Auto-AVSR's hypotheses or one of demo_phrases.txt
                          (nothing is generated; "" when the clip could not be read),
    "method":             "visual_gate" | "lm_fusion" | "visual_fallback" | "failed",
    "alternatives":       up to 4 other candidate sentences the user can pick instead (raw_text first),
    "needs_confirmation": True unless the recogniser itself independently produced exactly the gated phrase,
    "latency_ms":         wall time of this call,
    "details":            scores (all named *_uncalibrated: they are log scores, NOT probabilities), timings, errors,
}

The app must show final_text to the user and speak it only after the user confirms or edits it:
this module never speaks anything. needs_confirmation=False only means a one-tap confirm may be offered.

Strategy frozen in FROZEN below (see eval/frozen_config.json for versions and hashes):
  1. Auto-AVSR beam search (beam 10) gives the 10-best and the encoder output (computed once);
  2. visual phrase gate: the 8 phrases of demo_phrases.txt are scored against the SAME encoder output; if the best
     phrase beats the runner-up by margin_threshold nats per token, it is the answer;
  3. otherwise Qwen2.5-1.5B-Instruct scores each distinct hypothesis and the winner maximises
     visual_score + lm_weight * lm_logprob (noisy-channel fusion; the LM only scores, it never writes);
  4. any failure of step 3 (model missing, CUDA error...) falls back to the visual result; step 2/3 failures never
     lose the raw recognition.
`lip_read(video_path) -> str` in lipreading.py is unchanged and independent of this module.
"""

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # must be set before torch is imported, see lipreading.py
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

PHRASES_FILE = Path(__file__).with_name("demo_phrases.txt")
MAX_ALTERNATIVES = 4

FROZEN = {
    "version": "phase3-1",
    "vsr": {"checkpoint": "vsr_trlrs2lrs3vox2avsp_base.pth", "beam_size": 10, "decoder_weight": 0.9, "ctc_weight": 0.1, "nbest": 10},
    "gate": {"feature": "margin_per_token", "threshold": 1.0,
             "note": "best phrase minus runner-up, both scored as (0.9*decoder + 0.1*ctc) / n_tokens, in nats per token"},
    "fusion": {"lm_weight": 0.5, "visual_score": "0.9*decoder + 0.1*ctc, summed over tokens", "dedupe": "by normalised words",
               "max_candidates": 10, "tie_break": "earlier (better visual) hypothesis"},
    "lm": {"name": "Qwen/Qwen2.5-1.5B-Instruct", "revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306", "dtype": "bfloat16",
           "prefix": "Sentence that I silently mouthed, written in lowercase without punctuation:"},
    "phrases": {"file": "backend/demo_phrases.txt", "count": 8, "sha256_16": "ef5e8c22ccf848bd"},
    "confirmation": {"auto_confirm_eligible_only_if": "method == visual_gate and normalised raw_text == normalised final_text"},
}


def config_fingerprint(config=FROZEN):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


# ---- text helpers --------------------------------------------------------------------
def normalize_words(text):
    text = re.sub(r"[^a-z0-9' ]", " ", str(text).lower().replace("’", "'"))
    return [w.strip("'") for w in text.split() if w.strip("'")]


def _key(text):
    return tuple(normalize_words(text))


def dedupe(nbest, limit=None):
    """n-best entries in beam order -> distinct sentences (by normalised words), best first."""
    seen, out = set(), []
    for h in nbest:
        k = _key(h["text"])
        if k and k not in seen:
            seen.add(k)
            out.append(h)
        if limit and len(out) == limit:
            break
    return out


def phrases_sha(phrases):
    return hashlib.sha256("\n".join(phrases).encode()).hexdigest()[:16]


def load_phrases(path=PHRASES_FILE):
    try:
        return [p.strip() for p in Path(path).read_text().splitlines() if p.strip()]
    except OSError:
        return []


# ---- scores (log scores, uncalibrated) -------------------------------------------------
def visual_sum(e, cfg=FROZEN):
    return cfg["vsr"]["decoder_weight"] * e["dec"] + cfg["vsr"]["ctc_weight"] * e["ctc"]


def visual_per_token(e, cfg=FROZEN):
    return visual_sum(e, cfg) / e["n_tok"]


# ---- the decision (pure: no GPU, no files) ----------------------------------------------
def failure(reason, error=None, extra=None):
    return {"raw_text": "", "final_text": "", "method": "failed", "alternatives": [], "needs_confirmation": True,
            "latency_ms": 0, "details": {"reason": reason, "error": error, **(extra or {})}}


def choose(nbest, phrases, lm_logprobs, cfg=FROZEN):
    """Pick the final text.

    nbest: [{"text", "dec", "ctc", "n_tok"}] in beam order (best first).
    phrases: the same fields for each predefined phrase (scored against this clip's encoder output), or None.
    lm_logprobs: callable(list of texts) -> list of LM log-probs, or None when no LM is available.
    """
    if not nbest:
        return failure("no_hypotheses")
    raw_text = nbest[0]["text"]
    details = {"visual_score_per_token_uncalibrated": visual_per_token(nbest[0], cfg), "gate": None, "fusion": None,
               "lm_error": None, "lm_ms": None}
    gate_cfg = cfg["gate"]

    # 1. visual phrase gate
    if phrases and len(phrases) >= 2:
        ranked = sorted(phrases, key=lambda p: -visual_per_token(p, cfg))
        margin = visual_per_token(ranked[0], cfg) - visual_per_token(ranked[1], cfg)
        accepted = margin >= gate_cfg["threshold"]
        details["gate"] = {"best_phrase": ranked[0]["text"], "runner_up": ranked[1]["text"], "threshold": gate_cfg["threshold"],
                           "margin_per_token_uncalibrated": margin, "accepted": accepted}
        if accepted:
            final = ranked[0]["text"]
            same = _key(final) == _key(raw_text)
            alts = _alternatives(final, [raw_text, ranked[1]["text"]] + [h["text"] for h in dedupe(nbest)])
            details["reasons"] = [] if same else ["the recogniser's own reading differs from the matched phrase"]
            return _result(raw_text, final, "visual_gate", alts, not same, details)

    # 2. LM likelihood fusion (select-only), falling back to the visual result on any failure
    cands = dedupe(nbest, cfg["fusion"]["max_candidates"])
    if lm_logprobs is not None:
        try:
            t = time.perf_counter()
            lm = lm_logprobs([h["text"] for h in cands])
            details["lm_ms"] = (time.perf_counter() - t) * 1000
            if len(lm) != len(cands) or any(x != x or x in (float("inf"), float("-inf")) for x in lm):
                raise ValueError("LM returned an invalid score")
            w = cfg["fusion"]["lm_weight"]
            fused = [visual_sum(h, cfg) + w * l for h, l in zip(cands, lm)]
            best = max(range(len(cands)), key=lambda i: (fused[i], -i))
            details["fusion"] = {"lm_weight": w, "candidates": [
                {"text": h["text"], "visual_score_uncalibrated": visual_sum(h, cfg), "lm_logprob": l, "fused_score_uncalibrated": f}
                for h, l, f in zip(cands, lm, fused)]}
            order = sorted(range(len(cands)), key=lambda i: (-fused[i], i))
            final = cands[best]["text"]
            alts = _alternatives(final, [raw_text] + [cands[i]["text"] for i in order])
            details["changed_from_raw"] = _key(final) != _key(raw_text)
            details["reasons"] = ["no phrase matched confidently; text chosen by visual + language-model scores (both uncalibrated)"]
            return _result(raw_text, final, "lm_fusion", alts, True, details)
        except Exception as e:  # LM missing, CUDA error, bad scores: the visual result still stands
            details["lm_error"] = f"{type(e).__name__}: {e}"
    details["reasons"] = ["language model unavailable; showing the recogniser's own reading"]
    alts = _alternatives(raw_text, [h["text"] for h in cands])
    return _result(raw_text, raw_text, "visual_fallback", alts, True, details)


def _alternatives(final, pool):
    out, seen = [], {_key(final)}
    for text in pool:
        k = _key(text)
        if k and k not in seen:
            seen.add(k)
            out.append(text)
        if len(out) == MAX_ALTERNATIVES:
            break
    return out


def _result(raw_text, final, method, alternatives, needs_confirmation, details):
    return {"raw_text": raw_text, "final_text": final, "method": method, "alternatives": alternatives,
            "needs_confirmation": needs_confirmation, "latency_ms": 0, "details": details}


# ---- the pipeline object (models loaded once) ---------------------------------------------------
class Pipeline:
    def __init__(self, load_lm=True, warmup=True, phrases_path=PHRASES_FILE, lm_name=None, lm_revision=None):
        t0 = time.perf_counter()
        import lipreading  # loads Auto-AVSR + MediaPipe and warms up (module import, once per process)

        self.lipreading = lipreading
        self.vsr_load_s = time.perf_counter() - t0
        assert (lipreading.DECODER_WEIGHT, lipreading.CTC_WEIGHT, lipreading.BEAM_SIZE, lipreading.NBEST_KEEP) == (
            FROZEN["vsr"]["decoder_weight"], FROZEN["vsr"]["ctc_weight"], FROZEN["vsr"]["beam_size"], FROZEN["vsr"]["nbest"]), \
            "lipreading.py no longer matches the frozen configuration"
        self.phrases_path = phrases_path
        self.lm, self.lm_error, self.lm_load_s = None, None, None
        self.lm_lock = threading.Lock()
        if load_lm:
            t = time.perf_counter()
            try:
                from lm_fusion import MODEL_NAME, MODEL_REVISION, LocalLM

                self.lm = LocalLM(lm_name or MODEL_NAME, lm_revision or MODEL_REVISION)
                self.lm_load_s = time.perf_counter() - t
            except Exception as e:  # no Qwen: recognition still works, visually
                self.lm_error = f"{type(e).__name__}: {e}"
        if warmup:
            self.warm_up()

    def warm_up(self):
        """First-use CUDA costs, paid at start-up instead of on the first user clip."""
        import torch

        self.lipreading.score_token_sequences(torch.randn(50, 768, device=self.lipreading.DEVICE), [[10, 20, 30]])
        if self.lm:
            with self.lm_lock:
                self.lm.text_logprobs(["warm up"])

    def _lm_fn(self):
        if not self.lm:
            return None

        def run(texts):
            with self.lm_lock:
                return self.lm.text_logprobs(texts)
        return run

    def recognize(self, video_path):
        t0 = time.perf_counter()
        L = self.lipreading
        try:
            res = L.lip_read_detailed(str(video_path))
        except Exception as e:  # lip_read_detailed reports problems itself; this is only a last resort
            out = failure("error", f"{type(e).__name__}: {e}")
            out["latency_ms"] = (time.perf_counter() - t0) * 1000
            return out
        timings = dict(res.timings_ms)
        if res.reason != "ok" or not res.nbest:
            out = failure(res.reason, res.error, {"frames": {"n_frames": res.frames.n_frames, "missing_frac": res.frames.missing_frac}})
            out["latency_ms"] = (time.perf_counter() - t0) * 1000
            out["details"]["timings_ms"] = timings
            return out
        nbest = [{"text": h.text, "dec": h.decoder_logprob, "ctc": h.ctc_logprob, "n_tok": h.n_scored_tokens} for h in res.nbest]

        phrases, gate_error, phrases_ok = None, None, True
        listed = load_phrases(self.phrases_path)
        if len(listed) >= 2:
            phrases_ok = phrases_sha(listed) == FROZEN["phrases"]["sha256_16"]
            try:
                t = time.perf_counter()
                scored = L.score_candidates(res, listed)  # reuses the encoder output: no second video pass
                timings["phrase_scoring_ms"] = (time.perf_counter() - t) * 1000
                phrases = [{"text": p, "dec": s.decoder_logprob, "ctc": s.ctc_logprob, "n_tok": s.n_scored_tokens}
                           for p, s in zip(listed, scored) if s.valid]
            except Exception as e:  # the gate is an optimisation; recognition continues without it
                gate_error = f"{type(e).__name__}: {e}"
        t = time.perf_counter()
        out = choose(nbest, phrases, self._lm_fn())
        timings["decision_total_ms"] = (time.perf_counter() - t) * 1000
        timings["lm_scoring_ms"] = out["details"].get("lm_ms")
        timings["routing_overhead_ms"] = timings["decision_total_ms"] - (timings["lm_scoring_ms"] or 0)
        out["details"].update({"timings_ms": timings, "gate_error": gate_error, "phrases_match_frozen": phrases_ok,
                               "lm_load_error": self.lm_error, "config": FROZEN["version"] + ":" + config_fingerprint()})
        out["latency_ms"] = (time.perf_counter() - t0) * 1000
        return out


_pipeline = None
_pipeline_lock = threading.Lock()


def get_pipeline(**kwargs):
    """The process-wide pipeline: models are loaded on the first call and reused."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = Pipeline(**kwargs)
        return _pipeline


def recognize(video_path):
    return get_pipeline().recognize(video_path)
