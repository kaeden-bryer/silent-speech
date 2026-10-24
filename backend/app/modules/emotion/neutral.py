from __future__ import annotations

from pathlib import Path

from app.schemas import Emotion

from .base import EmotionDetector


class NeutralEmotion(EmotionDetector):
    """Always neutral."""

    name = "neutral"

    def detect(self, video_path: Path | None, text: str) -> Emotion:
        return Emotion()
