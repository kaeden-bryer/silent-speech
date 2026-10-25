"""Track 3 (extra): fix the lip reader's sentence with a small LLM running on the Ascent.

Input:  raw_text  the lip reader's guess, e.g. "can i half a coffee wiz oat milk"
        history   the conversation so far, oldest first:
                  [{"speaker": "me", "text": "..."}, {"speaker": "them", "text": "..."}]
Output: what the user meant, e.g. "Can I have a coffee with oat milk?"

How: Qwen3-4B-Instruct-2507 on the GPU, fully local: no internet once the weights are cached.
Picked over LFM2.5-1.2B, Qwen2.5-1.5B and Ministral-3-3B on 24 test sentences: the only one
that also fixed call/glass/bad and used the conversation ("i fell sick" -> "I feel sick" after
"How are you feeling?", but kept after "What happened last week?"). Smaller and faster:
LLM_MODEL=Qwen/Qwen2.5-1.5B-Instruct.
The prompt is rules + worked examples, some where only the conversation tells what was meant.
Fast: the fixed part of the prompt (rules + examples) is run once, at import, and reused, so each
sentence only costs its own few tokens. Greedy decoding.
Safe: every change the model makes is checked word by word (keep_lip_edits). A word may only
become one that looks alike on the lips, so it can fix the lip reader but never change what
was meant ("I need some water" for "i need some health" is undone).
server.py runs it first, then correction.py snaps the result to demo_phrases.txt.
Setup: models/MANIFEST.md.  Try sentences on their own:  python llm_correction.py "see you leader"
"""

import copy
import os
import re
import sys
import threading
import time
from difflib import SequenceMatcher

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen3-4B-Instruct-2507")  # 8 GB
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"  # CPU works too, just slowly
CONTEXT = 4  # how many earlier lines of the conversation the model reads
LOOKALIKE = 0.75  # 0-1: how alike on the lips a word and its replacement must be

RULES = """You correct sentences from a lip-reading AI, used by a person who cannot speak.
The AI sees lips but hears nothing, so it confuses words that look the same on the lips \
(p/b/m, f/v, t/d/n/s/z/l, k/g/h, similar vowels), and it writes in lowercase without punctuation.

Use the conversation so far to work out what the person most likely meant.
Reply with only the corrected sentence, with capitals and punctuation.
Keep every word that already fits. Only replace words that do not fit, with words that look the same on the lips.
Never answer, comment on or explain the sentence."""

EXAMPLES = [  # (conversation so far, lip reader, what they meant). About half need no change
    ("", "can i half a coffee wiz oat milk", "Can I have a coffee with oat milk?"),
    ("", "what time is it", "What time is it?"),
    ("Them: Do you want sugar in it?", "no thanks i am fine", "No thanks, I am fine."),
    ("", "where is the bat room", "Where is the bathroom?"),
    ("Them: Where are you from?", "i am from vrance", "I am from France."),
    ("", "could you kelp me", "Could you help me?"),
    ("Them: What did you do this weekend?", "i went to the meach", "I went to the beach."),
    ("", "the weather is nice today", "The weather is nice today."),
    ("Them: Is it ready yet?", "not yet give me five minutes", "Not yet, give me five minutes."),
    ("", "i cant find my geys", "I can't find my keys."),
    ("Them: Did you sleep well?", "no i was up all dight", "No, I was up all night."),
    ("", "it is dime to go", "It is time to go."),
    ("Them: Want to grab lunch?", "sure i am starfing", "Sure, I am starving."),
    ("", "blease close the door", "Please close the door."),
    ("Them: How was the movie?", "it was really fun", "It was really fun."),
    ("", "i love this song", "I love this song."),
]
DROPPED = {"a", "an", "the", "to", "of", "is", "am", "are", "it"}  # small words a lip reader can miss
GROUPS = ["pbm", "fv", "tdnszl", "kgcqxhjy", "wr", "aeiou"]  # letters that look alike on the lips
VISEMES = str.maketrans("".join(GROUPS), "".join(g[0] * len(g) for g in GROUPS))

tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.bfloat16).to(DEVICE).eval()
gpu = threading.Lock()


def turn(conversation, raw_text):
    fix = f"Lip reader output to fix: {raw_text}"
    return f"Conversation so far:\n{conversation}\n\n{fix}" if conversation else fix


def chat(raw_text, history):
    messages = [{"role": "system", "content": RULES}]
    for conversation, heard, meant in EXAMPLES:
        messages += [{"role": "user", "content": turn(conversation, heard)}, {"role": "assistant", "content": meant}]
    conversation = "\n".join(f'{"Me" if h["speaker"] == "me" else "Them"}: {h["text"]}' for h in history[-CONTEXT:])
    return messages + [{"role": "user", "content": turn(conversation, raw_text)}]


def tokens(messages):
    extra = {"enable_thinking": False} if "Qwen3" in MODEL else {}  # hybrid Qwen3 models: answer straight away
    return tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_dict=True, return_tensors="pt", **extra
    )["input_ids"].to(DEVICE)


# The rules + examples, run once: the tokens that two different sentences start with never change.
a, b = tokens(chat("yes", []))[0], tokens(chat("no", []))[0]
prefix = a[None, : int((a[: len(b)] == b[: len(a)]).int().cumprod(0).sum())]
with torch.no_grad():
    prefix_cache = model(prefix, use_cache=True).past_key_values  # the model picks its own cache type


def lips(text):
    """What a word looks like on the lips: "good" and "cood" both give "kat"."""
    text = re.sub(r"[^a-z]", "", text.lower())
    for pair, sound in (("th", "t"), ("ph", "f"), ("ck", "k"), ("sh", "s"), ("ch", "s")):
        text = text.replace(pair, sound)
    return re.sub(r"(.)\1+", r"\1", text.translate(VISEMES))


def keep_lip_edits(raw_text, fixed):
    """The model's sentence, with every change a lip reader could not have caused undone:
    a word may only become one that looks alike, nothing is dropped, only a DROPPED word may be added."""
    end = re.search(r"[.!?]*$", fixed).group()
    new_words, raw = fixed[: len(fixed) - len(end)].split(), raw_text.split()
    if new_words and not re.match(r"I\b", new_words[0]):
        new_words[0] = new_words[0][0].lower() + new_words[0][1:]  # it may not stay first
    key = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
    if SequenceMatcher(None, lips(raw_text), lips(fixed)).ratio() < 0.6:  # a different sentence altogether
        new_words, end = raw, "."
    match = SequenceMatcher(None, [key(w) for w in raw], [key(w) for w in new_words], autojunk=False)
    words = []
    for op, i1, i2, j1, j2 in match.get_opcodes():
        old, new = raw[i1:i2], new_words[j1:j2]
        alike = SequenceMatcher(None, lips(" ".join(old)), lips(" ".join(new))).ratio() >= LOOKALIKE
        allowed = op == "equal" or (op == "replace" and alike) or (op == "insert" and all(key(w) in DROPPED for w in new))
        words += new if allowed else old
    if words:
        words[0] = words[0][0].upper() + words[0][1:]
    return " ".join(words) + end


def llm_correct(raw_text: str, history: list[dict]) -> str:
    if not raw_text.strip():
        return raw_text
    ids = tokens(chat(raw_text, history))
    cache = copy.deepcopy(prefix_cache) if torch.equal(ids[:, : prefix.shape[1]], prefix) else None
    with gpu, torch.no_grad():
        out = model.generate(
            ids, attention_mask=torch.ones_like(ids), past_key_values=cache,
            max_new_tokens=min(64, 3 * len(raw_text.split()) + 10), do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    text = tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True).strip().splitlines()
    text = text[0].strip(' "') if text else ""
    return keep_lip_edits(raw_text, text) if text else raw_text


llm_correct("hello", [])  # warm-up: the first GPU run is slow


if __name__ == "__main__":
    for sentence in sys.argv[1:]:
        start = time.perf_counter()
        fixed = llm_correct(sentence, [])
        print(f"{sentence!r} -> {fixed!r} ({(time.perf_counter() - start) * 1000:.0f} ms)")
