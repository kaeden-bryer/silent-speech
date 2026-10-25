"""Live demo: say the lines of demo_script.txt (one per line, in order) instead of the raw lip reading.

streaming.py hands over the sure words as they come. The first ones are compared with the start
of every line; once one line clearly fits, that line's own words are said, as far as the lips have
got, and the rest of it at the release. So "that is the dream that silent speed" is said as
"That is the dream that Silent Speech", then "brings to life.".
Words are compared twice: as written, and as they look on the lips ("speech" and "speed" look
alike), so the lip reader's lookalike mistakes cost little. The line after the last one said
gets a bonus: the demo goes in order.
Off script (nothing fits after a few words), the raw words are said as usual.

    follow = start()        # a new hold of the button
    hear(follow, words)     # streaming.py's sure words -> the words to say now
    finish(follow, words)   # the release, with streaming.finish()'s words -> the words still to say
    shown(follow, pending)  # (heard, pending) for the phone's captions
Try it:  python script.py "that is the dream that silent speed"
"""

import re
import sys
from pathlib import Path

from rapidfuzz import fuzz, utils

SCRIPT = Path(__file__).with_name("demo_script.txt")
LOCK = 78  # 0-100: how alike the words so far and a line's start must be to say that line
MARGIN = 8  # and how far ahead of the next best line it must be (lines can start alike: "This is...")
LAST = 75  # at the release, a lower bar: no more words are coming
NEXT = 5  # bonus for the line after the last one said
MIN_WORDS = 2  # one word fits too many lines
GIVE_UP = 7  # words read without a line fitting: off script, say them raw
GROUPS = ["pbm", "fv", "tdnszl", "kgcqxhjy", "wr", "aeiou"]  # same as llm_correction.py (which loads an LLM)
VISEMES = str.maketrans("".join(GROUPS), "".join(g[0] * len(g) for g in GROUPS))

next_line = 0  # the line expected next, across holds


def lips(text):
    """What words look like on the lips: "speech" and "speed" both give "safat"."""
    text = re.sub(r"[^a-z]", "", text.lower())
    for pair, sound in (("th", "t"), ("ph", "f"), ("ck", "k"), ("sh", "s"), ("ch", "s")):
        text = text.replace(pair, sound)
    return re.sub(r"(.)\1+", r"\1", text.translate(VISEMES))


def alike(a, b):
    a, b = " ".join(a), " ".join(b)
    return (fuzz.ratio(a, b, processor=utils.default_process) + fuzz.ratio(lips(a), lips(b))) / 2


def place(raw, line):
    """(score, k): how well the raw words fit the line's first k words, for the best k.
    The lip reader drops and splits words, so k may differ from len(raw) by a couple."""
    return max(((alike(raw, line[:k]), -k) for k in range(max(1, len(raw) - 2), min(len(line), len(raw) + 2) + 1)),
               default=(0, 0))


def lines():
    return [line.split() for line in SCRIPT.read_text().splitlines() if line.strip()]  # re-read: edit it live


def pick(raw, bar):
    """The line the raw words start, or None if no line clearly fits."""
    scores = sorted(((place(raw, line)[0] + NEXT * (i == next_line), i) for i, line in enumerate(lines())), reverse=True)
    if not scores or scores[0][0] < bar:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < MARGIN and bar == LOCK:
        return None
    return scores[0][1]


def start():
    return {"raw": [], "line": None, "said": 0, "off": False}


def hear(follow, words):
    follow["raw"] += words
    if follow["off"]:
        return words
    script = lines()
    if follow["line"] is None:
        if len(follow["raw"]) < MIN_WORDS:
            return []
        follow["line"] = pick(follow["raw"], LOCK)
        if follow["line"] is None:
            if len(follow["raw"]) >= GIVE_UP:  # off script: everything held back, raw
                follow["off"] = True
                return follow["raw"]
            return []
    line = script[follow["line"]]
    upto = min(-place(follow["raw"], line)[1], len(line) - 1)  # the line's last word waits for the release
    say = line[follow["said"]:upto]
    follow["said"] = max(follow["said"], upto)
    return say


def finish(follow, words):
    global next_line
    follow["raw"] += words
    if follow["off"]:
        return words
    if follow["line"] is None and follow["raw"]:
        follow["line"] = pick(follow["raw"], LAST)
    if follow["line"] is None:
        return follow["raw"]  # nothing fits: the raw words, as without a script
    next_line = follow["line"] + 1
    return lines()[follow["line"]][follow["said"]:]


def shown(follow, pending):
    """The captions: the line's words said so far, and the raw words not said yet."""
    if follow["off"]:
        return " ".join(follow["raw"]), pending
    if follow["line"] is None:  # held back until a line fits
        return "", " ".join(follow["raw"] + pending.split())
    return " ".join(lines()[follow["line"]][:follow["said"]]), pending


if __name__ == "__main__":
    for raw in sys.argv[1:]:
        follow, words = start(), raw.lower().split()
        said = [w for i in range(1, len(words) + 1) for w in hear(follow, words[i - 1:i])]
        print(f"{raw!r} -> {' '.join(said)!r} + at the release {' '.join(finish(follow, []))!r}")
