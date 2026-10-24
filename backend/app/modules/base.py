"""Base class shared by every module implementation."""

from abc import ABC


class Module(ABC):
    name: str = "unnamed"  # shown in /api/health and in each response's `stages`

    def load(self) -> None:
        """Called once at startup: load models, read API keys, create clients.

        Raise if this implementation can't work here (missing key, package, model file...).
        The app logs the reason and uses the module's fallback instead.
        """
