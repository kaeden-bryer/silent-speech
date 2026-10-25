"""Text normalisation, WER/CER and manifest parsing for the VSR evaluation. No torch here, so it
can be tested without loading the model.

Normalisation (applied identically to ground truth and predictions): lowercase, curly
apostrophes to ', hyphens to spaces, everything except a-z 0-9 ' and spaces removed, spaces
collapsed, apostrophes trimmed from token edges. Digits are NOT spelled out: "2" and "two" differ.

WER and CER are corpus-level (total edits / total reference length), not the mean of per-clip
rates, so one short clip does not dominate. A clip with no prediction counts as all deletions.
"""

import csv
import re
from pathlib import Path

from rapidfuzz.distance import Levenshtein

SPLITS = {"dev", "test"}
LABEL_STATUSES = {"labeled", "no_speech", "unlabeled"}
OPTIONAL_COLUMNS = ["clip_id", "speaker_id", "speech_mode", "split", "set", "pair_id", "take", "label_status"]
MODALITY_TAGS = {"silent", "audible"}
CONTENT_TAGS = {"predefined", "unseen", "no_speech"}
TAGS = MODALITY_TAGS | CONTENT_TAGS


def normalize_text(text):
    text = (text or "").lower().replace("’", "'").replace("-", " ")
    text = re.sub(r"[^a-z0-9' ]", " ", text)
    return " ".join(w.strip("'") for w in text.split() if w.strip("'"))


def word_errors(ref, hyp):
    """(errors, substitutions, deletions, insertions) between normalised strings, by word."""
    ops = Levenshtein.editops(ref.split(), hyp.split()).as_list()
    kinds = [o[0] for o in ops]
    return len(ops), kinds.count("replace"), kinds.count("delete"), kinds.count("insert")


def char_errors(ref, hyp):
    return Levenshtein.distance(ref, hyp)


def clip_metrics(truth, prediction, nbest_texts=()):
    """Per-clip numbers for a labelled speech clip. truth/prediction are raw (un-normalised)."""
    ref, hyp = normalize_text(truth), normalize_text(prediction)
    errors, sub, dele, ins = word_errors(ref, hyp)
    oracle = min([errors] + [word_errors(ref, normalize_text(t))[0] for t in nbest_texts])
    return {
        "truth_norm": ref, "pred_norm": hyp,
        "ref_words": len(ref.split()), "word_errors": errors, "subs": sub, "dels": dele, "ins": ins,
        "ref_chars": len(ref), "char_errors": char_errors(ref, hyp),
        "exact": int(ref == hyp), "oracle_word_errors": oracle,
    }


def _rate(num, den):
    return num / den if den else None


def summarize_group(rows):
    """Aggregate per-clip rows (dicts from the harness) of one group.

    Accuracy uses labelled speech rows only; no_speech rows get a false-alarm rate; unlabelled
    rows are counted and excluded from accuracy.
    """
    speech = [r for r in rows if r["labeled"] and not r["no_speech"]]
    quiet = [r for r in rows if r["no_speech"]]
    out = {
        "n_clips": len(rows),
        "n_labeled_speech": len(speech),
        "n_unlabeled": sum(not r["labeled"] for r in rows),
        "n_no_speech": len(quiet),
        "n_failed": sum(bool(r["error"]) or not r["pred_norm"] for r in speech),
    }
    words = sum(r["ref_words"] for r in speech)
    chars = sum(r["ref_chars"] for r in speech)
    out["wer"] = _rate(sum(r["word_errors"] for r in speech), words)
    out["cer"] = _rate(sum(r["char_errors"] for r in speech), chars)
    out["oracle_nbest_wer"] = _rate(sum(r["oracle_word_errors"] for r in speech), words)
    out["exact_match"] = _rate(sum(r["exact"] for r in speech), len(speech))
    out["sub_del_ins"] = [sum(r[k] for r in speech) for k in ("subs", "dels", "ins")] if speech else None
    out["mean_clip_wer"] = _rate(sum(_rate(r["word_errors"], r["ref_words"]) or 0 for r in speech), len(speech))
    # no_speech: how often the pipeline produced text although nothing was said
    out["no_speech_false_alarm_rate"] = _rate(sum(bool(r["pred_norm"]) for r in quiet), len(quiet))
    for key in ("corrected_exact", "corrected_word_errors"):
        if speech and key in speech[0]:
            out[key] = sum(r[key] for r in speech)
    if speech and "corrected_word_errors" in speech[0]:
        out["corrected_wer"] = _rate(out["corrected_word_errors"], words)
        out["corrected_exact_match"] = _rate(out["corrected_exact"], len(speech))
    return out


def percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q / 100
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def latency_summary(rows, key):
    values = [r[key] for r in rows if r.get(key) is not None]
    if not values:
        return None
    return {"n": len(values), "mean": sum(values) / len(values), "p50": percentile(values, 50),
            "p95": percentile(values, 95), "max": max(values)}


def parse_tags(category):
    tags = {t.strip().lower() for t in re.split(r"[+|;]", category) if t.strip()}
    return tags


def load_manifest(path, phrases=()):
    """Read the CSV manifest: columns video_path, text, category.

    category: tags joined by + (or | or ;), from silent, audible, predefined, unseen, no_speech.
    Every row needs one content tag (predefined, unseen or no_speech); speech rows need exactly
    one modality tag. text is the ground truth, copied as given. An empty text on a speech row
    means "not labelled": the clip is still run (latency, n-best) but excluded from accuracy.
    no_speech rows must have empty text: that is a *labelled* empty transcript, not a missing label.

    Optional columns (written by eval/recorder): clip_id, speaker_id, speech_mode, split (dev|test),
    set, pair_id, take, label_status (labeled|no_speech|unlabeled). When present they are
    validated against the tags and text, so a mislabelled row fails loudly instead of being
    scored wrongly. If a split column exists every row needs one.
    Returns (rows, warnings); raises ValueError listing every problem.
    """
    path = Path(path)
    problems, warnings, rows = [], [], []
    known = {normalize_text(p) for p in phrases}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = {"video_path", "text", "category"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing column(s) {sorted(missing)}; need video_path,text,category")
        for line, rec in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            video = (rec["video_path"] or "").strip()
            text = (rec["text"] or "").strip()
            tags = parse_tags(rec["category"] or "")
            if not video:
                problems.append(f"{where}: empty video_path")
                continue
            if tags - TAGS:
                problems.append(f"{where}: unknown tag(s) {sorted(tags - TAGS)}; allowed {sorted(TAGS)}")
                continue
            content = tags & CONTENT_TAGS
            if len(content) != 1:
                problems.append(f"{where}: need exactly one of {sorted(CONTENT_TAGS)}, got {sorted(content)}")
            modality = tags & MODALITY_TAGS
            if "no_speech" not in tags and len(modality) != 1:
                problems.append(f"{where}: speech rows need exactly one of {sorted(MODALITY_TAGS)}, got {sorted(modality)}")
            if len(modality) > 1:
                problems.append(f"{where}: both silent and audible given")
            if "no_speech" in tags and text:
                problems.append(f"{where}: no_speech row has text {text!r}; leave it empty")
            if "no_speech" not in tags and not text:
                warnings.append(f"{where}: no ground truth; will be run but not scored")
            elif text and known:
                in_list = normalize_text(text) in known
                if "predefined" in tags and not in_list:
                    warnings.append(f"{where}: tagged predefined but {text!r} is not in demo_phrases.txt")
                if "unseen" in tags and in_list:
                    warnings.append(f"{where}: tagged unseen but {text!r} is in demo_phrases.txt")
            extra = {k: (rec.get(k) or "").strip() for k in OPTIONAL_COLUMNS if k in (reader.fieldnames or [])}
            if "split" in extra and extra["split"] not in SPLITS:
                problems.append(f"{where}: split must be one of {sorted(SPLITS)}, got {extra['split']!r}")
            status = extra.get("label_status")
            if status:
                if status not in LABEL_STATUSES:
                    problems.append(f"{where}: label_status must be one of {sorted(LABEL_STATUSES)}, got {status!r}")
                elif (status == "no_speech") != ("no_speech" in tags):
                    problems.append(f"{where}: label_status {status!r} contradicts category {rec['category']!r}")
                elif "no_speech" not in tags and (status == "labeled") != bool(text):
                    problems.append(f"{where}: label_status {status!r} contradicts text {text!r}")
            mode = extra.get("speech_mode")
            if mode and mode != ("none" if "no_speech" in tags else next(iter(modality), None)):
                problems.append(f"{where}: speech_mode {mode!r} contradicts category {rec['category']!r}")
            video_path = Path(video).expanduser()
            if not video_path.is_absolute():
                video_path = path.parent / video_path
            rows.append({
                "video_path": str(video_path), "text": text, "category": "+".join(sorted(tags)),
                "tags": sorted(tags), "labeled": bool(text) or "no_speech" in tags,
                "no_speech": "no_speech" in tags, **extra,
            })
    if problems:
        raise ValueError("manifest problems:\n  " + "\n  ".join(problems))
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows, warnings


def group_keys(row):
    """Names of the report groups a result row belongs to (besides ALL)."""
    keys = list(row["tags"])
    if "+" in row["category"]:
        keys.append(row["category"])
    for col in ("split", "set"):
        if row.get(col):
            keys.append(f"{col}:{row[col]}")
    return keys


def pair_report(rows):
    """Compare clips that share a pair_id: audible vs silent versions of one sentence, and the
    two sentences of a contrast pair. For contrast pairs, closer_to_own says whether the
    prediction is nearer (fewer word errors) to its own sentence than to its partner's."""
    pairs = {}
    for r in rows:
        if r.get("pair_id") and r["labeled"] and not r["no_speech"]:
            pairs.setdefault(r["pair_id"], []).append(r)
    out = []
    for pair_id, members in sorted(pairs.items()):
        if len(members) < 2:
            continue
        entries = []
        for r in members:
            entry = {"clip_id": r.get("clip_id", ""), "speech_mode": r.get("speech_mode", ""), "truth": r["truth_norm"],
                     "prediction": r["pred_norm"], "word_errors": r["word_errors"], "ref_words": r["ref_words"]}
            if r.get("set") == "contrast":
                others = [m for m in members if m is not r and m["truth_norm"] != r["truth_norm"]]
                if others:
                    own, other = r["word_errors"], word_errors(others[0]["truth_norm"], r["pred_norm"])[0]
                    entry["errors_vs_partner_sentence"] = other
                    entry["closer_to_own"] = own < other if own != other else None
            entries.append(entry)
        out.append({"pair_id": pair_id, "clips": entries})
    return out
