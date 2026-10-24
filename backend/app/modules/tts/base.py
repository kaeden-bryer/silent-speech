from __future__ import annotations

from abc import abstractmethod

from app.modules.base import Module
from app.schemas import Emotion, SpeechAudio


class TTSEngine(Module):
    @abstractmethod
    def synthesize(self, text: str, emotion: Emotion) -> SpeechAudio | None:
        """Speak `text` with a tone matching `emotion`.

        Return audio bytes (set mime_type): it's served at /api/audio/<id> and played by the
        browser, and by Twilio during phone calls. Return None to let the browser speak the
        text with its built-in voice. Runs in a worker thread.
        """
