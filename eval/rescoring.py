"""Rescoring and routing functions for the lip-reading experiments. No torch: they work on the
scores cached by rescoring_experiment.py, so they are cheap to test.

Entries are dicts with  text, dec (decoder log-prob incl. <eos>), ctc (CTC log-prob),
n_tok (tokens scored, incl. <eos>). They come from lipreading.lip_read_detailed (n-best) or
lipreading.score_candidates (phrases); both use the same conventions, checked in
eval/tests/test_candidate_scoring.py.

Score variants, all functions of (dec, ctc, n_tok):
    raw     = (1 - w_ctc) * dec + w_ctc * ctc
    "sum"   : raw                   (what beam search maximises when w_ctc = 0.1)
    "tok"   : raw / n_tok           (per-token average)
    "sqrt"  : raw / sqrt(n_tok)     (halfway between the two)
w_ctc = 0.1 with "sum" reproduces the beam's own ranking, so it cannot change an n-best order:
it is the baseline every other variant is compared with.
"""

import math

BASE_W = 0.1  # lipreading.CTC_WEIGHT
NORMS = ("sum", "tok", "sqrt")


def score(entry, w_ctc=BASE_W, norm="sum"):
    raw = (1 - w_ctc) * entry["dec"] + w_ctc * entry["ctc"]
    if norm == "sum":
        return raw
    if norm == "tok":
        return raw / entry["n_tok"]
    if norm == "sqrt":
        return raw / math.sqrt(entry["n_tok"])
    raise ValueError(f"unknown norm {norm!r}")


def rerank(nbest, w_ctc=BASE_W, norm="sum"):
    """Best hypothesis of an n-best list under a score variant (first wins ties)."""
    if not nbest:
        return None
    return max(nbest, key=lambda h: score(h, w_ctc, norm))


def ranked(entries, w_ctc=BASE_W, norm="sum"):
    return sorted(entries, key=lambda h: -score(h, w_ctc, norm))


def phrase_choice(phrases, w_ctc=BASE_W, norm="sum"):
    """(best phrase, runner-up or None) among the scored predefined phrases."""
    order = ranked(phrases, w_ctc, norm)
    return (order[0], order[1] if len(order) > 1 else None) if order else (None, None)


def routing_features(free, phrases):
    """Numbers a router can use to decide 'is this one of the predefined phrases?'.

    free: the open-vocabulary best hypothesis (beam order). phrases: scored phrases.
    gap_*: how much worse the best phrase is than the free decode (>= 0 means the free decode
           scores better; a negative gap means the phrase outscores it). Small gap = the
           phrase explains the video nearly as well as the best open-vocabulary reading.
    margin_*: best phrase minus second-best phrase (how decisively one phrase wins).
    """
    best_sum, second_sum = phrase_choice(phrases, BASE_W, "sum")
    best_tok, second_tok = phrase_choice(phrases, BASE_W, "tok")
    return {
        "phrase": best_sum["text"],
        "gap_sum": score(free, BASE_W, "sum") - score(best_sum, BASE_W, "sum"),
        "margin_sum": score(best_sum, BASE_W, "sum") - score(second_sum, BASE_W, "sum"),
        "phrase_tok": best_tok["text"],
        "gap_tok": score(free, BASE_W, "tok") - score(best_tok, BASE_W, "tok"),
        "margin_tok": score(best_tok, BASE_W, "tok") - score(second_tok, BASE_W, "tok"),
        "free_tok": score(free, BASE_W, "tok"),
    }


def route(free, phrases, feature, threshold):
    """Output text of a gated hybrid: the best phrase if the gate accepts, else the free decode.

    feature: "gap_sum" or "gap_tok" (accept when gap <= threshold), or "margin_sum" /
    "margin_tok" (accept when margin >= threshold).
    """
    f = routing_features(free, phrases)
    if feature.startswith("gap"):
        accept = f[feature] <= threshold
    else:
        accept = f[feature] >= threshold
    phrase = f["phrase_tok"] if feature.endswith("tok") else f["phrase"]
    return (phrase, True) if accept else (free["text"], False)


def auroc(positives, negatives):
    """P(random positive scores higher than random negative); ties count half. None if empty."""
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))
