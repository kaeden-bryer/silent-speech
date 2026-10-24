"""Track 3: fix the lip reader's mistakes.

Input:  raw_text  the lip reader's guess, e.g. "can i half a coffee wiz oat milk"
        history   the conversation so far, oldest first:
                  [{"speaker": "me", "text": "..."}, {"speaker": "them", "text": "..."}]
Output: what the user meant, e.g. "Can I have a coffee with oat milk?"

How: snap the guess to the closest sentence in demo_phrases.txt (one per line).
Lip reading gets open-ended sentences wrong a lot; a known list makes the demo reliable.
If nothing is close enough, the raw text goes through unchanged.
"""

from pathlib import Path

from rapidfuzz import fuzz, process, utils

PHRASES = Path(__file__).with_name("demo_phrases.txt")
THRESHOLD = 70  # 0-100: lower snaps more often, but to the wrong phrase more often too


def correct(raw_text: str, history: list[dict]) -> str:
    phrases = [p for p in PHRASES.read_text().splitlines() if p.strip()]  # re-read: edit it live
    match = process.extractOne(raw_text, phrases, scorer=fuzz.ratio, processor=utils.default_process)
    if match and match[1] >= THRESHOLD:
        return match[0]
    return raw_text
