"""The recording plan: which clips to record, with ground truth, split and instructions.

Deterministic: the same demo_phrases.txt always gives the same plan, so every speaker records
the same clips and clip IDs mean the same thing. 40 clips:

    16  predefined   the 8 phrases of backend/demo_phrases.txt, two takes each (silent)
    10  unseen       open-vocabulary sentences that are not in demo_phrases.txt (silent)
     6  contrast     three sentence pairs that differ in a small, easily lip-read-wrong way (silent)
     4  no_speech    nothing is said; ground truth is "" (a labelled empty transcript)
     4  audible      the same sentence spoken aloud, each paired with a silent clip above

Splits (development "dev" vs held-out "test"). Never tune thresholds, prompts or matching
rules on "test"; look at it once, at the end.
    * predefined: take 1 -> dev, take 2 -> test (same phrases, different recordings)
    * unseen: sentences are disjoint between splits (first 5 dev, last 5 test), so a sentence
      seen while tuning never reappears in test
    * contrast: a pair stays in one split (pairs 1 and 2 dev, pair 3 test)
    * no_speech: 2 dev, 2 test
    * audible: inherits the split of its silent partner
"""

import hashlib
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHRASES_FILE = ROOT / "backend" / "demo_phrases.txt"
SEED = 20261024  # fixes the recording order

UNSEEN = [  # 1-5 dev, 6-10 test. Everyday, short, no digits.
    "Could you open the window please?",
    "I would like a glass of water.",
    "My phone is on the table.",
    "What time does the store close?",
    "Please turn left at the corner.",
    "I am feeling a little tired today.",
    "Can you help me find my keys?",
    "The weather looks nice this morning.",
    "I will call you back in ten minutes.",
    "Where is the nearest bathroom?",
]

# (pair id, why it is hard, sentence a, sentence b)
CONTRAST = [
    ("contrast01", "negation: one short word reverses the meaning",
     "I can come to the meeting.", "I cannot come to the meeting."),
    ("contrast02", "opposites: on/off look alike on the lips",
     "Please turn the lights on.", "Please turn the lights off."),
    ("contrast03", "b/p look identical on the lips: bark vs park",
     "The bark was very loud.", "The park was very loud."),
]

NO_SPEECH = [  # (instruction, split)
    ("Motionless face: look at the camera, mouth closed, do not move.", "dev"),
    ("Mouth closed: blink and nod or turn your head slowly. Do not speak.", "dev"),
    ("Non-speech mouth movement: chew, lick your lips, or yawn. Do not speak.", "test"),
    ("Motionless face again: look at the camera, mouth closed, do not move.", "test"),
]

# audible clips: (silent partner clip id, why)
AUDIBLE_PARTNERS = ["pre01_t1", "pre05_t1", "uns01", "uns06"]

MODE_INSTRUCTIONS = {
    "silent": "Mouth the sentence with NO sound. Keep your mouth closed before and after.",
    "audible": "Say the sentence ALOUD at a normal volume. Keep your mouth closed before and after.",
    "none": "Do NOT speak or mouth any words.",
}
DURATION_HINT = "Recording is 2-6 seconds: press record, wait a beat, then do it, then stop."


def load_phrases(path=PHRASES_FILE):
    return [p.strip() for p in Path(path).read_text().splitlines() if p.strip()]


def phrases_sha(phrases):
    return hashlib.sha256("\n".join(phrases).encode()).hexdigest()[:16]


def _item(clip_id, set_, text, mode, split, take=1, pair_id="", instruction=None):
    tags = {"predefined": "predefined", "unseen": "unseen", "contrast": "unseen",
            "no_speech": "no_speech", "audible": None}[set_]
    return {
        "clip_id": clip_id, "set": set_, "text": text, "speech_mode": mode, "split": split,
        "take": take, "pair_id": pair_id, "tags": tags,
        "instruction": instruction or MODE_INSTRUCTIONS[mode],
        "label_status": "no_speech" if set_ == "no_speech" else "labeled",
    }


def build_plan(phrases=None):
    """Returns the 40 plan items in recording order."""
    phrases = phrases if phrases is not None else load_phrases()
    if len(phrases) != 8:
        raise ValueError(f"the plan is built for exactly 8 demo phrases, got {len(phrases)}")
    known = {p.lower() for p in phrases}
    items = []
    for i, text in enumerate(phrases, 1):
        for take, split in ((1, "dev"), (2, "test")):
            items.append(_item(f"pre{i:02d}_t{take}", "predefined", text, "silent", split, take))
    for i, text in enumerate(UNSEEN, 1):
        items.append(_item(f"uns{i:02d}", "unseen", text, "silent", "dev" if i <= 5 else "test"))
    for pair_id, why, a, b in CONTRAST:
        split = "test" if pair_id == "contrast03" else "dev"
        for letter, text in (("a", a), ("b", b)):
            items.append(_item(f"{pair_id}{letter}", "contrast", text, "silent", split, pair_id=pair_id,
                               instruction=f"{MODE_INSTRUCTIONS['silent']} (Pair: {why}.)"))
    for i, (instruction, split) in enumerate(NO_SPEECH, 1):
        items.append(_item(f"nos{i:02d}", "no_speech", "", "none", split, instruction=instruction))
    by_id = {it["clip_id"]: it for it in items}
    for i, partner in enumerate(AUDIBLE_PARTNERS, 1):
        p = by_id[partner]
        pair = f"audible{i:02d}"
        p["pair_id"] = pair  # the silent partner shares the pair id
        aud = _item(f"aud{i:02d}", "audible", p["text"], "audible", p["split"], pair_id=pair)
        aud["tags"] = p["tags"]  # predefined/unseen, like its silent partner
        items.append(aud)
    problems = validate_plan(items, known)
    if problems:
        raise ValueError("bad plan: " + "; ".join(problems))
    return order_for_recording(items)


def order_for_recording(items):
    """Silent clips first in a seeded shuffle (no sentence twice in a row, no_speech spread out),
    then the audible block, so the speaker switches mode once."""
    rng = random.Random(SEED)
    silent = [it for it in items if it["speech_mode"] != "audible"]
    audible = [it for it in items if it["speech_mode"] == "audible"]
    for _ in range(1000):
        rng.shuffle(silent)
        if all(a["text"] != b["text"] or not a["text"] for a, b in zip(silent, silent[1:])):
            break
    else:
        raise RuntimeError("could not order clips")
    return silent + audible


def validate_plan(items, known_phrases):
    problems = []
    counts = {}
    for it in items:
        counts[it["set"]] = counts.get(it["set"], 0) + 1
    expected = {"predefined": 16, "unseen": 10, "contrast": 6, "no_speech": 4, "audible": 4}
    if counts != expected:
        problems.append(f"counts {counts} != {expected}")
    ids = [it["clip_id"] for it in items]
    if len(set(ids)) != len(ids):
        problems.append("duplicate clip ids")
    for it in items:
        if it["set"] in ("unseen", "contrast") and it["text"].lower() in known_phrases:
            problems.append(f"{it['clip_id']} text is in demo_phrases.txt")
        if it["set"] == "no_speech" and it["text"]:
            problems.append(f"{it['clip_id']} no_speech must have empty text")
        if it["set"] != "no_speech" and not it["text"]:
            problems.append(f"{it['clip_id']} missing text")
    return problems


def manifest_category(item):
    """The evaluate.py tag string, e.g. 'silent+predefined', 'audible+unseen', 'no_speech'."""
    if item["set"] == "no_speech":
        return "no_speech"
    return f"{item['speech_mode']}+{item['tags']}"
