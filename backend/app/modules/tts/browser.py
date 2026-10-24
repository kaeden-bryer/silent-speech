from __future__ import annotations

from app.schemas import Emotion, SpeechAudio

from .base import TTSEngine


class BrowserTTS(TTSEngine):
    """No server-side audio: the frontend speaks with the device's voice (speechSynthesis).

    The emotion -> pitch/rate mapping for this case lives in frontend/js/player.js.
    """

    name = "browser"

    def synthesize(self, text: str, emotion: Emotion) -> SpeechAudio | None:
        return None
