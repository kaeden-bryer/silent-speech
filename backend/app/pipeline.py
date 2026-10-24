"""Runs one utterance through the modules.

    video -> lipreading -+-> correction -----------+-> tts -> audio URL -> (telephony, if in a call)
                         +-> emotion (in parallel) +

Every module call goes through `_run`: if the selected implementation raises, the
module's fallback runs instead and the error is reported in `stages`. A broken module
degrades the result; it never takes the app down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.audio_store import AudioStore
from app.loader import Slot
from app.schemas import Emotion, StageReport, Transcript, UtteranceResult
from app.sessions import Session

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        lipreading: Slot,
        correction: Slot,
        emotion: Slot,
        tts: Slot,
        telephony: Slot,
        audio_store: AudioStore,
    ) -> None:
        self.lipreading = lipreading
        self.correction = correction
        self.emotion = emotion
        self.tts = tts
        self.telephony = telephony
        self.audio_store = audio_store
        self._background: set[asyncio.Task] = set()

    @property
    def slots(self) -> list[Slot]:
        return [self.lipreading, self.correction, self.emotion, self.tts, self.telephony]

    async def from_video(self, session: Session, video_path: Path) -> UtteranceResult:
        start = time.perf_counter()
        # No fallback at runtime: if the real lip reader crashes on a clip, speaking a mock
        # sentence would put words in the user's mouth. Return "nothing understood" instead.
        transcript, report = await _run(
            self.lipreading, "transcribe", video_path, on_error=Transcript(text="")
        )
        return await self._finish(session, transcript.text, video_path, [report], start, True)

    async def from_text(self, session: Session, text: str, correct: bool = True) -> UtteranceResult:
        """Typed text stands in for the lip reader's output (testing, or typing as a backup)."""
        return await self._finish(session, text, None, [], time.perf_counter(), correct)

    async def _finish(
        self,
        session: Session,
        raw_text: str,
        video_path: Path | None,
        stages: list[StageReport],
        start: float,
        correct: bool,
    ) -> UtteranceResult:
        raw_text = raw_text.strip()
        text, emotion, audio_url = "", Emotion(), None

        if raw_text:
            # Emotion detection runs while the (network-bound) correction call is in flight.
            emotion_job = asyncio.create_task(_run(self.emotion, "detect", video_path, raw_text))
            text = raw_text
            if correct:
                text, report = await _run(self.correction, "correct", raw_text, session.context())
                stages.append(report)
            emotion, report = await emotion_job
            stages.append(report)
            text = text.strip()

        if text:
            audio, report = await _run(self.tts, "synthesize", text, emotion)
            stages.append(report)
            if audio is not None:
                audio_url = f"/api/audio/{self.audio_store.put(audio)}"
            session.add_turn("user", text)

        result = UtteranceResult(
            session_id=session.id,
            raw_text=raw_text,
            text=text,
            emotion=emotion,
            audio_url=audio_url,
            stages=stages,
            total_ms=_ms_since(start),
        )
        if session.call_id and text:
            # In the background: the caller gets its response without waiting for the phone line.
            task = asyncio.create_task(self._say_into_call(session, result))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return result

    async def _say_into_call(self, session: Session, result: UtteranceResult) -> None:
        try:
            await asyncio.to_thread(self.telephony.impl.say, session, result)
        except Exception:
            log.exception("telephony (%s) failed to say the sentence", self.telephony.impl.name)


async def _run(slot: Slot, method: str, *args: Any, on_error: Any = None) -> tuple[Any, StageReport]:
    """Call `method` on the slot's implementation in a worker thread, with fallback on error."""
    start = time.perf_counter()
    try:
        result = await asyncio.to_thread(getattr(slot.impl, method), *args)
        return result, StageReport(stage=slot.kind, impl=slot.impl.name, ms=_ms_since(start))
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        log.exception("%s (%s) failed", slot.kind, slot.impl.name)
        if on_error is not None:
            return on_error, StageReport(
                stage=slot.kind, impl=slot.impl.name, ms=_ms_since(start), error=error
            )
        if slot.impl is slot.fallback:
            raise
        result = await asyncio.to_thread(getattr(slot.fallback, method), *args)
        return result, StageReport(
            stage=slot.kind, impl=slot.fallback.name, ms=_ms_since(start), error=error
        )


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)
