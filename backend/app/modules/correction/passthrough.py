from __future__ import annotations

from app.schemas import ConversationContext

from .base import TextCorrector


class Passthrough(TextCorrector):
    """Returns the text unchanged."""

    name = "passthrough"

    def correct(self, raw_text: str, context: ConversationContext) -> str:
        return raw_text
