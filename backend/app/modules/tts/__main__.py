"""Try a TTS on its own, without the server (defaults to TTS from .env).
Writes the audio to backend/data/tts/:

    python -m app.modules.tts "Hi, nice to meet you!" --emotion happy
"""

import argparse
import time
import typing

from app.config import DATA_DIR, Settings
from app.loader import instantiate
from app.schemas import Emotion, EmotionLabel

from . import IMPLEMENTATIONS

EXTENSIONS = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/ogg": ".ogg"}

parser = argparse.ArgumentParser(description="Run one TTS implementation on a sentence.")
parser.add_argument("text")
parser.add_argument("--impl", default=Settings().tts, choices=IMPLEMENTATIONS)
parser.add_argument("--emotion", default="neutral", choices=typing.get_args(EmotionLabel))
parser.add_argument("--intensity", type=float, default=0.8)
args = parser.parse_args()

engine = instantiate(__package__, IMPLEMENTATIONS[args.impl])
engine.load()
start = time.perf_counter()
audio = engine.synthesize(args.text, Emotion(label=args.emotion, intensity=args.intensity))
print(f"{(time.perf_counter() - start) * 1000:.0f} ms")

if audio is None:
    print("No audio returned: the browser would speak this text itself.")
else:
    out = DATA_DIR / "tts" / f"{args.impl}_{args.emotion}{EXTENSIONS.get(audio.mime_type, '.bin')}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio.data)
    print(f"Wrote {out}")
