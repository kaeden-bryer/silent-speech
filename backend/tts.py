"""Track 3: text to speech.

Input:  text     what to say
        emotion  "neutral", "happy", "sad", "angry" or "surprised"
Output: MP3 audio as bytes, or None to let the browser read the text with its own voice.

How: Kokoro-82M, running locally on the GPU (no internet needed once the weights are cached).
"""

import io
import os
import threading

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py

import numpy as np
import soundfile as sf
from kokoro import KPipeline

VOICE = "af_heart"
SAMPLE_RATE = 24000
SPEED = {"happy": 1.1, "surprised": 1.1, "sad": 0.9}  # a small hint of emotion

pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
gpu = threading.Lock()


def text_to_speech(text: str, emotion: str) -> bytes | None:
    if not text.strip():
        return None
    with gpu:
        chunks = [audio.numpy() for _, _, audio in pipeline(text, voice=VOICE, speed=SPEED.get(emotion, 1.0))]
    out = io.BytesIO()
    sf.write(out, np.concatenate(chunks), SAMPLE_RATE, format="MP3")
    return out.getvalue()


text_to_speech("Ready.", "neutral")  # warm-up: the first GPU run is slow
