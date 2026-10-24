"""In-memory conversation state, one per browser session id. Lost on restart (fine for a demo)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import ConversationContext, Speaker, Turn


@dataclass
class Session:
    id: str
    turns: list[Turn] = field(default_factory=list)
    call_id: str | None = None  # set while a phone call is active

    def add_turn(self, speaker: Speaker, text: str) -> None:
        self.turns.append(Turn(speaker=speaker, text=text))

    def context(self, max_turns: int = 12) -> ConversationContext:
        return ConversationContext(turns=self.turns[-max_turns:])


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]
