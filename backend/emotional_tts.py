"""Track 3 (live): an instant voice that sounds like the face looks.

Input:  text     what to say
        emotion  "neutral", "energetic", "sad" or "angry" (what emotion.py returns)
        hurry    1 = normal speed; more when the voice is behind the lips (server.py decides)
Output: (WAV audio as bytes, its length in seconds), or (None, 0) to let the browser read the text.

How: the same Kokoro-82M as tts.py (~40 ms a sentence on the GPU), but the emotion changes how it
speaks, not only how fast. Before making the sound, Kokoro predicts the sentence's pitch curve (Hz,
80 points a second); that curve is bent per emotion (STYLES): higher and livelier when energetic,
lower and flatter when sad, wider and more emphatic when angry. Then loudness, and for anger a
little grit. The ~0.4 s of silence Kokoro puts before every sentence and ~0.5 s after it are cut,
so pieces said one after another follow each other without gaps.
Hear the styles:  python emotional_tts.py "testing from mobile"  (writes one .wav per emotion)
"""

import io
import os
import sys
import threading
import time

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py

import numpy as np
import soundfile as sf
import torch
from kokoro import KPipeline

VOICE = "af_heart"
SAMPLE_RATE = 24000
# pitch: x the average pitch   moves: x how far the pitch moves around it   speed: x speaking rate
# gain: loudness in dB         grit: >0 saturates a little (a tense, harsher voice)
STYLES = {  # strong on purpose: milder versions were not heard as different on the phone
    "neutral": dict(pitch=1.0, moves=1.0, speed=1.0, gain=0, grit=0),
    "energetic": dict(pitch=1.25, moves=1.8, speed=1.12, gain=2, grit=0),  # up ~4 semitones, bouncy
    "sad": dict(pitch=0.82, moves=0.35, speed=0.8, gain=-6, grit=0),  # down ~3.5 semitones, flat, slow, soft
    "angry": dict(pitch=0.95, moves=2.0, speed=1.15, gain=4, grit=3.0),  # lower than happy, loud, hard, clipped
}
VOICED = 50  # Hz: Kokoro's pitch curve is ~0 where the sound is unvoiced
PAD = 0.02  # seconds of silence kept at each end
FADE = 0.005  # seconds faded in and out
QUIET = 0.005  # below this, a sample counts as silence
PEAK = 0.7  # every piece's loudest point, before its emotion's gain (room left for anger's +3 dB)

pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cuda")
gpu = threading.Lock()
style = STYLES["neutral"]  # the style of the sentence being made (set under `gpu`)
predict_pitch = pipeline.model.predictor.F0Ntrain


def bent_pitch(x, s):
    """Kokoro's own pitch and energy prediction, with the pitch curve bent to `style`."""
    f0, n = predict_pitch(x, s)
    voiced = f0 > VOICED
    if voiced.any():
        mean = f0[voiced].mean()
        f0 = torch.where(voiced, (mean + (f0 - mean) * style["moves"]) * style["pitch"], f0).clamp(min=0)
    return f0, n


pipeline.model.predictor.F0Ntrain = bent_pitch  # this file's own Kokoro: tts.py's is untouched


def trim(audio):
    loud = np.flatnonzero(np.abs(audio) > QUIET)
    if not len(loud):
        return audio[:0]
    pad = int(PAD * SAMPLE_RATE)
    return audio[max(loud[0] - pad, 0): loud[-1] + pad]


def text_to_speech(text: str, emotion: str, hurry: float = 1.0):
    global style
    if not text.strip():
        return None, 0
    look = STYLES.get(emotion, STYLES["neutral"])
    with gpu:
        style = look
        chunks = [a.numpy() for _, _, a in pipeline(text, voice=VOICE, speed=look["speed"] * hurry)]
    audio = trim(np.concatenate(chunks)) if chunks else np.zeros(0, np.float32)
    if not len(audio):
        return None, 0
    audio = audio / max(np.abs(audio).max(), 1e-6)  # every piece as loud as the others
    if look["grit"]:
        audio = np.tanh(audio * look["grit"]) / np.tanh(look["grit"])
    audio = audio * PEAK * 10 ** (look["gain"] / 20)
    fade = min(int(FADE * SAMPLE_RATE), len(audio) // 2)
    audio[:fade] *= np.linspace(0, 1, fade)  # no click where a piece starts or stops
    audio[len(audio) - fade:] *= np.linspace(1, 0, fade)
    out = io.BytesIO()
    sf.write(out, np.clip(audio, -1, 1), SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return out.getvalue(), len(audio) / SAMPLE_RATE


text_to_speech("Ready.", "neutral")  # warm-up: the first GPU run is slow


if __name__ == "__main__":
    sentence = " ".join(sys.argv[1:]) or "testing from mobile"
    for feeling in STYLES:
        start = time.perf_counter()
        wav, seconds = text_to_speech(sentence, feeling)
        with open(f"{feeling}.wav", "wb") as f:
            f.write(wav)
        print(f"{feeling}.wav: {seconds:.2f}s of speech, made in {(time.perf_counter() - start) * 1000:.0f} ms")
