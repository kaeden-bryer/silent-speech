"""Shared data types: the contract between the modules, the pipeline and the frontend.

Every track depends on this file. Adding an optional field is safe; renaming or removing
one breaks other people's code, so tell the team first.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

EmotionLabel = Literal["neutral", "happy", "sad", "angry", "surprised", "fearful"]
Speaker = Literal["user", "other"]  # "user" = our user, "other" = the person they talk to


class Transcript(BaseModel):
    """Lip reader output: raw and noisy, the correction module cleans it up."""

    text: str
    confidence: float | None = None  # 0..1, if the model gives one


class Emotion(BaseModel):
    label: EmotionLabel = "neutral"
    intensity: float = 0.0  # 0..1


class Turn(BaseModel):
    speaker: Speaker
    text: str
    timestamp: float = Field(default_factory=time.time)


class ConversationContext(BaseModel):
    """What the corrector knows about the conversation so far, oldest turn first."""

    turns: list[Turn] = Field(default_factory=list)


class SpeechAudio(BaseModel):
    data: bytes
    mime_type: str = "audio/mpeg"


class StageReport(BaseModel):
    stage: str  # "lipreading", "correction", "emotion" or "tts"
    impl: str  # implementation that produced the result
    ms: float
    error: str | None = None  # set when the selected implementation failed


class UtteranceResult(BaseModel):
    session_id: str
    raw_text: str  # what the lip reader saw (or what was typed)
    text: str  # corrected text: what gets spoken. Empty = nothing understood
    emotion: Emotion
    audio_url: str | None  # None = the client speaks `text` with the browser's own voice
    stages: list[StageReport]
    total_ms: float


class ModuleStatus(BaseModel):
    kind: str
    requested: str  # from .env
    active: str  # what actually loaded
    fallback: bool  # True when `active` is the placeholder fallback (part not ready yet)
    error: str | None = None  # why `requested` failed to load
