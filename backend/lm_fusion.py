"""Local language-model scoring of lip-reading hypotheses (Qwen2.5-1.5B-Instruct, bf16, GPU).

Used by pipeline.py. The LM only SCORES sentences it is given: log P(sentence | a fixed prefix).
It never writes text. Everything is local: the weights are read from the Hugging Face cache
(local_files_only, pinned to one revision) and nothing is downloaded or sent anywhere.

The numbers are summed natural-log probabilities: a language prior, not a probability that the
sentence is what the person said. Combine them with the visual scores as pipeline.py does.
"""

import os
import re

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py: must be set before torch is imported
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"
MODEL_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"  # the cached snapshot the experiments used
PREFIX = "Sentence that I silently mouthed, written in lowercase without punctuation:"
MAX_TEXT_CHARS = 160


def sanitize(text, limit=MAX_TEXT_CHARS):
    """Untrusted text -> one printable line, no angle brackets, bounded length."""
    text = re.sub(r"[<>]", " ", str(text))
    text = re.sub(r"[^\x20-\x7e]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


class LocalLM:
    def __init__(self, name=MODEL_NAME, revision=MODEL_REVISION, device="cuda", _loaded=None):
        import torch

        self.torch, self.device = torch, device
        if _loaded:  # (model, tokenizer) already in memory, for tests
            self.model, self.tok = _loaded
        else:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tok = AutoTokenizer.from_pretrained(name, revision=revision, local_files_only=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                name, revision=revision, local_files_only=True, dtype=torch.bfloat16).to(device).eval()

    def text_logprobs(self, texts, prefix=PREFIX):
        """Sum of token log-probs of each text after `prefix` (no end-of-sentence term), one batched pass."""
        torch = self.torch
        prefix_ids = self.tok.encode(prefix, add_special_tokens=False)
        rows, spans = [], []
        for t in texts:
            ids = self.tok.encode(" " + sanitize(t), add_special_tokens=False)
            rows.append(prefix_ids + ids)
            spans.append((len(prefix_ids), len(rows[-1])))
        width = max(len(r) for r in rows)
        pad = self.tok.pad_token_id if self.tok.pad_token_id is not None else 0
        batch = torch.tensor([r + [pad] * (width - len(r)) for r in rows], device=self.device)
        mask = torch.tensor([[1] * len(r) + [0] * (width - len(r)) for r in rows], device=self.device)
        with torch.no_grad():
            logp = torch.log_softmax(self.model(input_ids=batch, attention_mask=mask).logits.float(), -1)
        return [float(logp[i, s - 1:e - 1].gather(-1, batch[i, s:e].unsqueeze(-1)).sum()) for i, (s, e) in enumerate(spans)]

    def memory_mib(self):
        return {"allocated": self.torch.cuda.memory_allocated() / 2**20, "peak": self.torch.cuda.max_memory_allocated() / 2**20}
