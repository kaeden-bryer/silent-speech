"""Fingerprints of everything the frozen pipeline depends on, shared by freeze_config.py and final_test.py.

Hard checks (a mismatch blocks the final test): the frozen strategy parameters, the source files, the model
files (Auto-AVSR checkpoint, face detector, Qwen weights), the phrase list. Soft checks (reported, not blocking):
library versions. Only hashes and metadata are read: no video, no manifest row, no test clip is opened here.
"""

import hashlib
import importlib.metadata as md
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SOURCES = ["backend/lipreading.py", "backend/pipeline.py", "backend/lm_fusion.py", "backend/demo_phrases.txt",
           "eval/vsr_metrics.py"]
LIBS = ["torch", "torchvision", "torchaudio", "transformers", "mediapipe", "rapidfuzz", "sentencepiece", "numpy", "opencv-python-headless",
        "scikit-image", "accelerate", "safetensors", "tokenizers"]
QWEN_CACHE = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-1.5B-Instruct"


def sha256(path, algo="sha256"):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def current_state(with_model_hashes=True):
    import pipeline as P

    state = {"strategy": P.FROZEN, "strategy_fingerprint": P.config_fingerprint(), "sources": {}, "models": {}, "libs": {}}
    for rel in SOURCES:
        state["sources"][rel] = sha256(ROOT / rel)
    if with_model_hashes:
        ckpt = ROOT / "models" / P.FROZEN["vsr"]["checkpoint"]
        state["models"]["auto_avsr_checkpoint"] = {"file": ckpt.name, "bytes": ckpt.stat().st_size, "md5": sha256(ckpt, "md5")}
        face = ROOT / "models" / "blaze_face_short_range.tflite"
        state["models"]["face_detector"] = {"file": face.name, "sha256": sha256(face)}
        snap = QWEN_CACHE / "snapshots" / P.FROZEN["lm"]["revision"]
        state["models"]["qwen"] = {"name": P.FROZEN["lm"]["name"], "revision": P.FROZEN["lm"]["revision"],
                                   "files": {f.name: sha256(f) for f in sorted(snap.iterdir()) if f.name in
                                             ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt")}}
        state["models"]["auto_avsr_repo_commit"] = run("git", "-C", str(ROOT / "third_party" / "auto_avsr"), "rev-parse", "HEAD")
    for lib in LIBS:
        try:
            state["libs"][lib] = md.version(lib)
        except md.PackageNotFoundError:
            state["libs"][lib] = None
    state["python"] = platform.python_version()
    return state


def compare(frozen, current):
    """(fatal mismatches, warnings)."""
    fatal, warn = [], []
    if frozen["strategy_fingerprint"] != current["strategy_fingerprint"]:
        fatal.append("strategy parameters (pipeline.FROZEN) differ from the frozen configuration")
    for rel, digest in frozen["sources"].items():
        if current["sources"].get(rel) != digest:
            fatal.append(f"source file changed since freezing: {rel}")
    for name, value in frozen["models"].items():
        if current["models"].get(name) != value:
            fatal.append(f"model changed since freezing: {name}")
    for lib, version in frozen["libs"].items():
        if current["libs"].get(lib) != version:
            warn.append(f"library version differs: {lib} {version} -> {current['libs'].get(lib)}")
    return fatal, warn


def git_info():
    return {"branch": run("git", "-C", str(ROOT), "branch", "--show-current"), "head": run("git", "-C", str(ROOT), "rev-parse", "HEAD"),
            "uncommitted_files": (run("git", "-C", str(ROOT), "status", "--porcelain") or "").splitlines()}


def gpu_info():
    return {"gpu": run("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader")}
