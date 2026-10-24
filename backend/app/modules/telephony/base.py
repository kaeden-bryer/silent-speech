from __future__ import annotations

from abc import abstractmethod

from fastapi import APIRouter

from app.modules.base import Module
from app.schemas import UtteranceResult
from app.sessions import Session


class Telephony(Module):
    """Contract for phone calls.

    The core already provides POST /api/call/start and /api/call/hangup (they call the
    methods below and keep `session.call_id` up to date) and calls `say` after every
    utterance while a call is active. Your implementation must also:

    - add what the other person says with `session.add_turn("other", text)`: the frontend
      shows it, and the corrector uses it as context;
    - set `session.call_id = None` when the call ends on its own (they hang up).

    Any extra routes you need (e.g. webhooks from your phone provider) go in `router`;
    it's mounted on the app at startup. Inside a route, get a session with
    `request.app.state.sessions.get(session_id)`.
    """

    router: APIRouter | None = None

    @abstractmethod
    def start_call(self, session: Session, to: str) -> str:
        """Dial `to` (E.164 format, e.g. +15551234567) and return a call id. Raise on failure."""

    @abstractmethod
    def hang_up(self, session: Session) -> None:
        """End the session's active call (`session.call_id`)."""

    @abstractmethod
    def say(self, session: Session, result: UtteranceResult) -> None:
        """Speak the user's sentence into the active call.

        `result.audio_url` is a path on this backend (prefix it with the public URL for the
        phone provider to fetch it), or None when the TTS made no audio: then speak
        `result.text` with the provider's own voice. Runs in a worker thread.
        """
