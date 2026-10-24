from __future__ import annotations

import itertools
from pathlib import Path

from app.schemas import Transcript

from .base import LipReader

# The kind of mistakes a lip reader makes: words that look alike on the lips.
SAMPLES = [
    "hello my name is sam nice too meat you",
    "can i half a coffee wiz oat milk",
    "wear is the train station",
    "thank you so much fur your help",
    "i am vary happy too be here",
]


class MockLipReader(LipReader):
    """Ignores the video and returns noisy sample sentences in turn."""

    name = "mock"

    def load(self) -> None:
        self._samples = itertools.cycle(SAMPLES)

    def transcribe(self, video_path: Path) -> Transcript:
        return Transcript(text=next(self._samples), confidence=0.0)
