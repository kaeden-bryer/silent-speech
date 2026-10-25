"""Connects everyone's files into the app. You shouldn't need to edit this one.

Run from backend/:  uvicorn server:app --reload --host 0.0.0.0 --port 8000
Offline phone demo: python server.py  (HTTPS when ../certs exists, see offline-demo-instructions.md)
"""

import base64
import importlib
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()  # API keys from backend/.env, read them with os.getenv("NAME")


def load(name):
    """Import a teammate's file. If it's broken (e.g. a missing package), carry on without it."""
    try:
        return importlib.import_module(name)
    except Exception:
        traceback.print_exc()
        return None


def safe(step, fallback):
    """Run one step. If it crashes, print the error and use `fallback`, so the rest still works."""
    try:
        return step()
    except Exception:
        traceback.print_exc()
        return fallback


lipreading = load("lipreading")
llm_correction = load("llm_correction")
correction = load("correction")
emotion = load("emotion")
tts = load("tts")
phone = load("phone")

app = FastAPI()
if phone:
    app.include_router(phone.router)

RECORDINGS = Path(__file__).parent / "recordings"  # every clip is kept: test material for lip reading
history = []  # the conversation: [{"speaker": "me" or "them", "text": "..."}]
call_active = False


def speak(raw_text, video_path=None):
    fixed = safe(lambda: llm_correction.llm_correct(raw_text, history), raw_text)  # the LLM fixes it
    text = safe(lambda: correction.correct(fixed, history), fixed)  # then snaps it to a demo phrase
    feeling = safe(lambda: emotion.detect_emotion(video_path, raw_text), "neutral")
    audio = safe(lambda: tts.text_to_speech(text, feeling), None)
    history.append({"speaker": "me", "text": text})
    if call_active:
        safe(lambda: phone.say(text, audio), None)
    return {
        "raw_text": raw_text,
        "text": text,
        "emotion": feeling,
        # MP3 as base64, or None: then the website reads `text` with the browser's voice
        "audio": base64.b64encode(audio).decode() if audio else None,
    }


@app.post("/api/video")
def from_video(video: UploadFile = File(...)):
    """One recorded clip = one sentence."""
    RECORDINGS.mkdir(exist_ok=True)
    suffix = ".mp4" if "mp4" in (video.content_type or "") else ".webm"
    path = RECORDINGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000}{suffix}"
    path.write_bytes(video.file.read())
    raw_text = safe(lambda: lipreading.lip_read(str(path)), "")
    if not raw_text:  # nothing understood: say nothing rather than something wrong
        return {"raw_text": "", "text": "", "emotion": "neutral", "audio": None}
    return speak(raw_text, str(path))


@app.post("/api/text")
def from_text(text: str = Body(embed=True)):
    """Typed text, used as if the lip reader had read it. Lets you test without the camera."""
    return speak(text)


@app.get("/api/history")
def get_history():
    return {"history": history, "call_active": call_active}


@app.post("/api/call")
def start_call(number: str = Body(embed=True)):
    global call_active
    try:
        phone.start_call(number, history)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    call_active = True
    return {"ok": True}


@app.post("/api/hangup")
def hang_up():
    global call_active
    safe(lambda: phone.hang_up(), None)
    call_active = False
    return {"ok": True}


# The website at http://localhost:8000: the built app (frontend/dist) when it exists,
# otherwise the raw frontend/ folder. Build with: cd frontend && npm install && npm run build
FRONTEND = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND / "dist" if (FRONTEND / "dist").is_dir() else FRONTEND, html=True))


if __name__ == "__main__":
    import uvicorn

    CERTS = Path(__file__).parent.parent / "certs"
    https = (CERTS / "server.pem").is_file() and (CERTS / "server.key").is_file()
    if https:
        print("Serving HTTPS on port 8000")
    else:
        print("No certs/ found, serving plain HTTP on port 8000 (run scripts/setup_network.sh certs for HTTPS)")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_certfile=str(CERTS / "server.pem") if https else None,
        ssl_keyfile=str(CERTS / "server.key") if https else None,
    )
