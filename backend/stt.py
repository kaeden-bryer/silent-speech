"""Track 4 (calls): what the person on the other end of the phone call says, as text.

Input:  audio  one utterance, float32 samples at 16 kHz (phone.py cuts the call audio into them)
Output: the words, or "" when nothing was understood
        phone.py adds them to the conversation: captions on the website, context for the corrections.

How: Whisper (large-v3-turbo) on the GPU through transformers, fully local once the weights
are cached. Not faster-whisper: CTranslate2 has no aarch64 CUDA build.
Phone audio is 8 kHz, so expect it to be a bit worse than with a good microphone.
On simulated call audio (8 kHz mu-law + hiss), large-v3-turbo made no real word errors where
distil-small.en did ("for me please" -> "from you, please"), at ~160 ms a sentence instead of ~45.
Try a recording on its own:  python stt.py clip.wav
"""

import os
import sys
import threading

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py

import numpy as np
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

MODEL = os.getenv("STT_MODEL", "openai/whisper-large-v3-turbo")  # smaller, faster: distil-whisper/distil-small.en
ENGLISH = {} if MODEL.endswith(".en") else {"language": "en", "task": "transcribe"}  # multilingual models: English
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"  # CPU works too, just slowly
SAMPLE_RATE = 16000
SHORTEST = 0.3  # seconds: anything shorter is a click or a breath, not words
# Whisper "hears" these in line noise and silence: never show them as something the person said
MADE_UP = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.", "bye.", "."}

processor = WhisperProcessor.from_pretrained(MODEL)
model = WhisperForConditionalGeneration.from_pretrained(
    MODEL, torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32
).to(DEVICE).eval()
gpu = threading.Lock()


def transcribe(audio: np.ndarray) -> str:
    if len(audio) < SHORTEST * SAMPLE_RATE:
        return ""
    features = processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
    with gpu, torch.inference_mode():
        ids = model.generate(features.to(DEVICE, model.dtype), max_new_tokens=128, **ENGLISH)
    text = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
    return "" if text.lower() in MADE_UP else text


transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))  # warm-up: the first GPU run is slow


if __name__ == "__main__":
    import soundfile as sf
    from scipy.signal import resample_poly

    samples, rate = sf.read(sys.argv[1], dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    print(transcribe(resample_poly(samples, SAMPLE_RATE, rate).astype(np.float32)) or "(nothing)")
