from __future__ import annotations

from app.schemas import UtteranceResult
from app.sessions import Session

from .base import Telephony


class DisabledTelephony(Telephony):
    """No phone calls. The call endpoints answer 503 and the rest of the app is unaffected."""

    name = "disabled"

    def start_call(self, session: Session, to: str) -> str:
        raise RuntimeError("phone calls are not set up (TELEPHONY=disabled)")

    def hang_up(self, session: Session) -> None:
        pass

    def say(self, session: Session, result: UtteranceResult) -> None:
        pass
