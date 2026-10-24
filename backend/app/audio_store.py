"""Keeps recent TTS clips in memory so the browser (and Twilio) can fetch them by URL."""

from __future__ import annotations

from collections import OrderedDict
from uuid import uuid4

from app.schemas import SpeechAudio


class AudioStore:
    def __init__(self, max_items: int = 100) -> None:
        self.max_items = max_items
        self._items: OrderedDict[str, SpeechAudio] = OrderedDict()

    def put(self, audio: SpeechAudio) -> str:
        audio_id = uuid4().hex
        self._items[audio_id] = audio
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
        return audio_id

    def get(self, audio_id: str) -> SpeechAudio | None:
        return self._items.get(audio_id)
