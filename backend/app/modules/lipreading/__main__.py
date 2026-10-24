"""Try a lip reader on its own, without the server (defaults to LIPREADING from .env):

    python -m app.modules.lipreading path/to/clip.webm [--impl mock]
"""

import argparse
import time
from pathlib import Path

from app.config import Settings
from app.loader import instantiate

from . import IMPLEMENTATIONS

parser = argparse.ArgumentParser(description="Run one lip reading implementation on a clip.")
parser.add_argument("video", type=Path)
parser.add_argument("--impl", default=Settings().lipreading, choices=IMPLEMENTATIONS)
args = parser.parse_args()

reader = instantiate(__package__, IMPLEMENTATIONS[args.impl])
reader.load()
start = time.perf_counter()
print(reader.transcribe(args.video))
print(f"{(time.perf_counter() - start) * 1000:.0f} ms")
