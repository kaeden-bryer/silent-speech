from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

from app.modules.base import Module
from app.schemas import Emotion


class EmotionDetector(Module):
    @abstractmethod
    def detect(self, video_path: Path | None, text: str) -> Emotion:
        """Guess the user's emotion for this sentence.

        `video_path` is the same clip the lip reader gets, or None for typed input.
        `text` is the raw (uncorrected) transcript. Runs in a worker thread, in parallel
        with the correction call.
        """
