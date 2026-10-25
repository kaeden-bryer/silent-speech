"""Verify eval/integration/server_patch.diff without touching the live app.

    python eval/integration/check_patched_server.py

Copies backend/ into a temporary directory, applies the patch to the COPY of server.py, imports that copy with FastAPI's test client
(no port is opened, the running server is not involved) and checks the confirm-then-speak flow on a synthetic clip (a still public-domain photo):
  - /api/video returns the recognition and NOTHING else happens: no audio, no history entry, no phone call;
  - /api/speak (the confirmed text) is the only route that makes audio, writes history and talks to the phone;
  - confirmed/edited text is spoken exactly as given (the fuzzy matcher must not rewrite it);
  - recognition still works if the pipeline is missing or crashes.
"""

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="ss_patched_"))
    try:
        backend = tmp / "backend"
        backend.mkdir()
        for name in ("server.py", "lipreading.py", "pipeline.py", "lm_fusion.py", "correction.py", "emotion.py", "tts.py", "phone.py", "demo_phrases.txt"):
            shutil.copy(ROOT / "backend" / name, backend / name)
        for link in ("models", "third_party", "frontend"):
            (tmp / link).symlink_to((ROOT / link).resolve())
        r = subprocess.run(["patch", "-p1", "--dry-run", "-i", str(HERE / "server_patch.diff")], cwd=tmp, capture_output=True, text=True)
        assert r.returncode == 0, "patch does not apply cleanly to the current backend/server.py:\n" + r.stdout + r.stderr
        subprocess.run(["patch", "-p1", "-s", "-i", str(HERE / "server_patch.diff")], cwd=tmp, check=True)
        print("patch applies cleanly to the current backend/server.py (on a copy)")

        sys.path.insert(0, str(backend))
        sys.path.insert(1, str(ROOT / "eval"))
        os.chdir(backend)
        import cv2
        import numpy as np
        from skimage import data
        from starlette.testclient import TestClient

        import server  # the patched copy: loads Auto-AVSR, Qwen (via pipeline) and Kokoro from the local cache

        assert server.pipeline is not None and server.pipeline.get_pipeline().lm is not None, "pipeline/Qwen did not load"
        clip = tmp / "clip.webm"
        w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"VP80"), 25, (512, 512))
        face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
        for _ in range(60):
            w.write(face)
        w.release()

        phone_calls = []
        server.phone.say = lambda text, audio: phone_calls.append(text)
        server.call_active = True
        client = TestClient(server.app)
        checks = []

        def check(name, ok, detail=""):
            checks.append(bool(ok))
            print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")

        r = client.post("/api/video", files={"video": ("clip", clip.read_bytes(), "video/webm")})
        body = r.json()
        keys = {"clip_id", "raw_text", "final_text", "method", "alternatives", "needs_confirmation", "latency_ms"}
        check("/api/video returns the recognition contract", r.status_code == 200 and keys <= set(body), f"(method {body.get('method')}, final {body.get('final_text')!r})")
        check("/api/video makes no audio", "audio" not in body)
        check("/api/video writes no history and starts no phone speech", server.history == [] and phone_calls == [])

        confirmed = "thank you very mush"  # the old fuzzy matcher would silently 'fix' this to a demo phrase
        r = client.post("/api/speak", json={"text": confirmed, "clip_id": body["clip_id"]})
        s = r.json()
        audio = base64.b64decode(s["audio"]) if s.get("audio") else b""
        check("/api/speak returns MP3 audio for the confirmed text", r.status_code == 200 and (audio[:3] == b"ID3" or (len(audio) > 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)), f"({len(audio)} bytes; ID3 tag or MPEG frame sync)")
        check("confirmed text is spoken exactly as given (no fuzzy rewrite)", s["text"] == confirmed and server.history == [{"speaker": "me", "text": confirmed}])
        check("phone speech only happens after confirmation", phone_calls == [confirmed])

        before = (len(server.history), len(phone_calls))
        r = client.post("/api/speak", json={"text": "   "})
        check("empty text is not spoken", r.json()["audio"] is None and (len(server.history), len(phone_calls)) == before)

        real = server.pipeline
        server.pipeline = None
        body2 = client.post("/api/video", files={"video": ("clip", clip.read_bytes(), "video/webm")}).json()
        check("pipeline missing: still recognises, marked for confirmation", body2["method"] == "visual_fallback" and body2["needs_confirmation"] and body2["final_text"] == body["raw_text"])
        server.pipeline = type("Broken", (), {"recognize": staticmethod(lambda p: 1 / 0)})
        body3 = client.post("/api/video", files={"video": ("clip", clip.read_bytes(), "video/webm")}).json()
        check("pipeline crashes: still recognises, marked for confirmation", body3["method"] == "visual_fallback" and body3["needs_confirmation"])
        server.pipeline = real
        body4 = client.post("/api/video", files={"video": ("clip", b"not a video", "video/webm")}).json()
        check("unreadable upload: empty text, nothing spoken", body4["final_text"] == "" and "audio" not in body4 and len(server.history) == 1)

        print("\nPATCH CHECK " + ("PASSED" if all(checks) else "FAILED"))
        return 0 if all(checks) else 1
    finally:
        os.chdir(HERE)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
