"""Try an emotion detector on its own, without the server (defaults to EMOTION from .env):

    python -m app.modules.emotion --video data/recordings/some_clip.webm
    python -m app.modules.emotion --text "i am so happy"
"""

import argparse
import time
from pathlib import Path

from app.config import Settings
from app.loader import instantiate

from . import IMPLEMENTATIONS

parser = argparse.ArgumentParser(description="Run one emotion implementation.")
parser.add_argument("--video", type=Path)
parser.add_argument("--text", default="")
parser.add_argument("--impl", default=Settings().emotion, choices=IMPLEMENTATIONS)
args = parser.parse_args()

detector = instantiate(__package__, IMPLEMENTATIONS[args.impl])
detector.load()
start = time.perf_counter()
print(detector.detect(args.video, args.text))
print(f"{(time.perf_counter() - start) * 1000:.0f} ms")
