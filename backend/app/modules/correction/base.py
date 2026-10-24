from __future__ import annotations

from abc import abstractmethod

from app.modules.base import Module
from app.schemas import ConversationContext


class TextCorrector(Module):
    @abstractmethod
    def correct(self, raw_text: str, context: ConversationContext) -> str:
        """Return the sentence the user most likely meant.

        `raw_text` comes from the lip reader (or was typed). `context.turns` holds the recent
        conversation, oldest first: speaker "user" is our user, "other" is the person they
        talk to (filled in during phone calls). Runs in a worker thread.
        """
