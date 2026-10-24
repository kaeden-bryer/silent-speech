from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

from app.modules.base import Module
from app.schemas import Transcript


class LipReader(Module):
    @abstractmethod
    def transcribe(self, video_path: Path) -> Transcript:
        """Read the lips in a short clip (one sentence) and return what was said.

        `video_path` is the browser's MediaRecorder output: .webm (Chrome, Android, Firefox)
        or .mp4 (Safari, iOS); front camera, about 640x480, variable frame rate, no audio.
        The file is deleted after the request, so don't keep the path around.
        Runs in a worker thread, so blocking code is fine.
        """
