"""HTTP API used by the frontend. Interactive docs at http://localhost:8000/docs when running."""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from app.config import DATA_DIR
from app.schemas import UtteranceResult

router = APIRouter(prefix="/api")


class TextUtterance(BaseModel):
    session_id: str
    text: str
    correct: bool = True  # False = speak the text exactly as typed


class StartCall(BaseModel):
    session_id: str
    to: str  # E.164 format, e.g. +15551234567


class HangUp(BaseModel):
    session_id: str


@router.get("/health")
def health(request: Request) -> dict:
    """Which implementation each module runs, and whether it's still the placeholder."""
    return {"ok": True, "modules": [slot.status().model_dump() for slot in request.app.state.pipeline.slots]}


@router.post("/utterance/video")
async def utterance_from_video(
    request: Request, session_id: str = Form(...), video: UploadFile = File(...)
) -> UtteranceResult:
    """One recorded clip (one sentence) -> text + audio."""
    state = request.app.state
    suffix = _video_suffix(video)
    data = await video.read()

    if state.settings.save_recordings:
        recordings = DATA_DIR / "recordings"
        recordings.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}_{session_id[:8]}{suffix}"
        (recordings / name).write_bytes(data)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / f"clip{suffix}"
        path.write_bytes(data)
        return await state.pipeline.from_video(state.sessions.get(session_id), path)


@router.post("/utterance/text")
async def utterance_from_text(body: TextUtterance, request: Request) -> UtteranceResult:
    """Typed text treated as lip reader output. Lets you test everything after lip reading."""
    state = request.app.state
    return await state.pipeline.from_text(state.sessions.get(body.session_id), body.text, body.correct)


@router.get("/audio/{audio_id}")
def get_audio(audio_id: str, request: Request) -> Response:
    audio = request.app.state.audio_store.get(audio_id)
    if audio is None:
        raise HTTPException(404, "Unknown or expired audio id")
    return Response(content=audio.data, media_type=audio.mime_type)


@router.get("/session/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    session = request.app.state.sessions.get(session_id)
    return {
        "session_id": session.id,
        "turns": [turn.model_dump() for turn in session.turns],
        "call_active": session.call_id is not None,
    }


@router.post("/session/{session_id}/reset")
def reset_session(session_id: str, request: Request) -> dict:
    request.app.state.sessions.get(session_id).turns.clear()
    return {"ok": True}


@router.post("/call/start")
async def start_call(body: StartCall, request: Request) -> dict:
    """While the call is active, every utterance of this session is also said into the call,
    and what the other person says shows up as "other" turns in GET /api/session/{id}."""
    state = request.app.state
    session = state.sessions.get(body.session_id)
    try:
        session.call_id = await asyncio.to_thread(state.pipeline.telephony.impl.start_call, session, body.to)
    except Exception as e:
        raise HTTPException(503, f"Could not start the call: {e}")
    return {"call_id": session.call_id}


@router.post("/call/hangup")
async def hang_up(body: HangUp, request: Request) -> dict:
    state = request.app.state
    session = state.sessions.get(body.session_id)
    await asyncio.to_thread(state.pipeline.telephony.impl.hang_up, session)
    session.call_id = None
    return {"ok": True}


def _video_suffix(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    if "mp4" in content_type or "quicktime" in content_type:
        return ".mp4"  # Safari / iOS
    if "webm" in content_type:
        return ".webm"  # Chrome, Firefox, Android
    return Path(upload.filename or "").suffix or ".webm"
