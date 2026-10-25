"""Connects everyone's files into the app. You shouldn't need to edit this one.

Run from backend/:  uvicorn server:app --reload --host 0.0.0.0 --port 8000
Offline phone demo: python server.py  (HTTPS when ../certs exists, see offline-demo-instructions.md)

Every sentence prints one line: what was read, what was said, and how long each step took.
"""

import base64
import importlib
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Request, UploadFile
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


def safe(step, fallback, timings, name):
    """Run one step and note how long it took (ms) in `timings[name]`.
    If it crashes, print the error and use `fallback`, so the rest still works."""
    start = time.perf_counter()
    try:
        return step()
    except Exception:
        traceback.print_exc()
        return fallback
    finally:
        timings[name] = round((time.perf_counter() - start) * 1000)


lipreading = load("lipreading")
llm_correction = load("llm_correction")
correction = load("correction")
emotion = load("emotion")
tts = load("tts")
phone = load("phone")

broken = [name for name in ("lipreading", "llm_correction", "correction", "emotion", "tts", "phone") if not globals()[name]]
print(f"Using the safe default for: {', '.join(broken)} (see the errors above)" if broken else "Every part loaded.", flush=True)

app = FastAPI()
if phone:
    app.include_router(phone.router)

RECORDINGS = Path(__file__).parent / "recordings"  # every clip is kept: test material for lip reading
NOTHING = {"raw_text": "", "text": "", "emotion": "neutral", "audio": None}  # nothing understood: say nothing
history = []  # the conversation: [{"speaker": "me" or "them", "text": "..."}]
call_active = False
meanwhile = ThreadPoolExecutor(4)  # steps that run next to the others instead of after them


def speak(raw_text, video_path=None, timings=None):
    timings = {} if timings is None else timings
    # The face doesn't depend on the text fixes, so it is looked at while the LLM works
    feeling = meanwhile.submit(safe, lambda: emotion.detect_emotion(video_path, raw_text), "neutral", timings, "emotion")
    fixed = safe(lambda: llm_correction.llm_correct(raw_text, history), raw_text, timings, "llm")  # the LLM fixes it
    text = safe(lambda: correction.correct(fixed, history), fixed, timings, "snap")  # then snaps it to a demo phrase
    feeling = feeling.result()
    audio = safe(lambda: tts.text_to_speech(text, feeling), None, timings, "tts")
    history.append({"speaker": "me", "text": text})
    if call_active:
        safe(lambda: phone.say(text, audio), None, timings, "phone")
    steps = ", ".join(f"{name} {ms}" for name, ms in timings.items())
    print(f"{raw_text!r} -> {text!r} ({feeling}) | ms: {steps}", flush=True)
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
    clip = video.file.read()
    if not clip:  # the phone sent an empty recording (stopped too fast)
        return NOTHING
    RECORDINGS.mkdir(exist_ok=True)
    suffix = ".mp4" if "mp4" in (video.content_type or "") else ".webm"
    path = RECORDINGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000}{suffix}"
    path.write_bytes(clip)
    timings = {}
    raw_text = safe(lambda: lipreading.lip_read(str(path)), "", timings, "lip")
    if not raw_text:  # nothing understood: say nothing rather than something wrong
        print(f"{path.name}: nothing read | ms: lip {timings['lip']}", flush=True)
        return NOTHING
    return speak(raw_text, str(path), timings)


@app.post("/api/text")
def from_text(text: str = Body(embed=True)):
    """Typed text, used as if the lip reader had read it. Lets you test without the camera."""
    if not text.strip():
        return NOTHING
    return speak(text.strip())


@app.get("/api/history")
def get_history():
    global call_active
    if call_active and not safe(lambda: phone.active(), True, {}, "phone"):
        call_active = False  # the other person hung up (or never answered)
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
    safe(lambda: phone.hang_up(), None, {}, "hangup")
    call_active = False
    return {"ok": True}


@app.middleware("http")
async def no_stale_page(request: Request, call_next):
    """The built JS/CSS (/assets/...) have a hash in their name, so phones can keep them forever.
    Everything else is checked again each time, so after a rebuild no phone is stuck on the old page."""
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# The website at http://localhost:8000: the built app (frontend/dist) when it exists,
# otherwise the raw frontend/ folder. Build with: cd frontend && npm install && npm run build
FRONTEND = Path(__file__).parent.parent / "frontend"
if not (FRONTEND / "dist").is_dir():
    print("frontend/dist is missing, so only /test.html works. Build the app: cd frontend && npm install && npm run build")
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
        timeout_keep_alive=75,  # keep the phone's connection open between sentences: no new TLS handshake each time
    )
