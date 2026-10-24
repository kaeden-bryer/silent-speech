"""Core settings, read from backend/.env.

Only the shared knobs live here. Module-specific settings (API keys, model paths...) are
read by each module itself with os.getenv, so adding one never requires touching this file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
DATA_DIR = BACKEND_DIR / "data"  # gitignored: recordings, test outputs

load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


@dataclass
class Settings:
    # Which implementation each module uses (see IMPLEMENTATIONS in each module's __init__.py).
    # The defaults are the placeholder fallbacks, so the app starts with no .env at all.
    lipreading: str = field(default_factory=lambda: _env("LIPREADING", "mock"))
    correction: str = field(default_factory=lambda: _env("CORRECTION", "passthrough"))
    emotion: str = field(default_factory=lambda: _env("EMOTION", "neutral"))
    tts: str = field(default_factory=lambda: _env("TTS", "browser"))
    telephony: str = field(default_factory=lambda: _env("TELEPHONY", "disabled"))

    # Keep every uploaded clip in backend/data/recordings/ (test material for the lip reader).
    save_recordings: bool = field(default_factory=lambda: _env("SAVE_RECORDINGS", "0") == "1")
