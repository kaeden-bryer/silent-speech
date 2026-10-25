"""Connects everyone's files into the app. You shouldn't need to edit this one.

Run from backend/:  uvicorn server:app --reload --host 0.0.0.0 --port 8000
Offline phone demo: python server.py  (HTTPS when ../certs exists, see offline-demo-instructions.md)

Every sentence prints one line: what was read, what was said, and how long each step took.
The website uses /api/live: lips are read while the button is held, and spoken word by word.
"""

import asyncio
import base64
import importlib
import json
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Request, UploadFile, WebSocket
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


# Off: live lip reading speaks words as they come, and the LLM rewrites whole sentences.
# True brings it back for /api/video and /api/text (it also costs ~1 min of start-up and 8 GB).
LLM_CORRECTION = False

lipreading = load("lipreading")
streaming = load("streaming")
llm_correction = load("llm_correction") if LLM_CORRECTION else None
correction = load("correction")
emotion = load("emotion")
emotional_tts = load("emotional_tts")
tts = load("tts")
phone = load("phone")

parts = ["lipreading", "streaming", "correction", "emotion", "emotional_tts", "tts", "phone"] + ["llm_correction"] * LLM_CORRECTION
broken = [name for name in parts if not globals()[name]]
print(f"Using the safe default for: {', '.join(broken)} (see the errors above)" if broken else "Every part loaded.", flush=True)

app = FastAPI()
if phone:
    app.include_router(phone.router)

RECORDINGS = Path(__file__).parent / "recordings"  # every clip is kept: test material for lip reading
NOTHING = {"raw_text": "", "text": "", "emotion": "neutral", "audio": None}  # nothing understood: say nothing
history = []  # the conversation: [{"speaker": "me" or "them", "text": "..."}]
call_active = False
meanwhile = ThreadPoolExecutor(4)  # steps that run next to the others instead of after them


def voice_of(text, feeling, hurry=1.0):
    """(audio, seconds): the emotional voice (WAV), or tts.py's (MP3, length unknown) if it isn't running."""
    if emotional_tts:
        return emotional_tts.text_to_speech(text, feeling, hurry)
    return tts.text_to_speech(text, feeling), 0


def speak(raw_text, video_path=None, timings=None):
    timings = {} if timings is None else timings
    # The face doesn't depend on the text fixes, so it is looked at while the LLM works
    feeling = meanwhile.submit(safe, lambda: emotion.detect_emotion(video_path, raw_text), "neutral", timings, "emotion")
    fixed = raw_text
    if llm_correction:  # the LLM fixes it (off, see LLM_CORRECTION)
        fixed = safe(lambda: llm_correction.llm_correct(raw_text, history), raw_text, timings, "llm")
    text = safe(lambda: correction.correct(fixed, history), fixed, timings, "snap")  # then snaps it to a demo phrase
    feeling = feeling.result()
    audio, _ = safe(lambda: voice_of(text, feeling), (None, 0), timings, "tts")
    history.append({"speaker": "me", "text": text})
    if call_active:
        safe(lambda: phone.say(text, audio), None, timings, "phone")
    steps = ", ".join(f"{name} {ms}" for name, ms in timings.items())
    print(f"{raw_text!r} -> {text!r} ({feeling}) | ms: {steps}", flush=True)
    return {
        "raw_text": raw_text,
        "text": text,
        "emotion": feeling,
        # WAV (or MP3) as base64, or None: then the website reads `text` with the browser's voice
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


@app.websocket("/api/live")
async def live(ws: WebSocket):
    """Live lip reading while the button is held (streaming.py does the reading).
    Phone -> here: {"type": "start"}, frames (8-byte time in ms + JPEG), {"type": "stop"}.
    Here -> phone: {"type": "heard", "heard", "pending", "face"} after each reading,
                   {"type": "say", "text", "audio"} for each group of sure words, in order,
                   {"type": "done", "text", "emotion"} once everything is said."""
    await ws.accept()
    sending = asyncio.Lock()

    async def send(message):
        async with sending:
            await ws.send_json(message)

    hold = reading = None
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                if hold and not hold["stopped"]:
                    streaming.add_frame(hold, message["bytes"])
            elif message.get("text"):
                kind = json.loads(message["text"]).get("type")
                if kind == "start" and not streaming:
                    await send({"type": "error", "message": "Live lip reading isn't running: see the server's terminal."})
                elif kind == "start":
                    if reading:
                        await reading  # the last hold is still being finished
                    hold = streaming.start()
                    reading = asyncio.create_task(read_live(hold, send))
                elif kind == "stop" and hold:
                    hold["stopped"] = True
    finally:
        if reading:
            reading.cancel()  # the phone went away


MAX_HOLD = 60  # seconds: stop reading even if the button is never released
FACE_EVERY = 0.6  # seconds between two looks at the face, so the voice follows its emotion
FACE_SECONDS = 1.6  # each look is at this many seconds of the latest video
BEHIND = 0.3  # seconds the voice may lag behind the lips before it speaks faster (up to x1.3)


async def read_live(hold, send):
    """Read while the button is held; voice the sure words as soon as they come, in the face's emotion."""
    begin = time.perf_counter()
    timings, said_at, reads = {}, [], []
    feeling = looking = seen = None  # the voice's emotion, the look at the face in progress, what it saw last
    looked_at = 0.0
    voicing = None  # the last group of words being voiced: each waits for the one before, to stay in order
    talking_until = 0.0  # when the phone will be done saying everything sent so far

    def look():
        return emotion.detect_emotion_frames(streaming.frames_so_far(hold, FACE_SECONDS))

    async def voice(words, before):
        nonlocal talking_until
        if before:
            await before
        mood = feeling or (await looking if looking else "neutral")  # the first words wait for the first look
        text = " ".join(words)
        hurry = min(1.3, 1 + max(0.0, talking_until - time.perf_counter() - BEHIND) * 0.5)
        audio, seconds = await asyncio.to_thread(safe, lambda: voice_of(text, mood, hurry), (None, 0), timings, "tts")
        talking_until = max(talking_until, time.perf_counter()) + seconds
        if call_active:  # in a thread: say() waits on this same event loop to send the audio
            await asyncio.to_thread(safe, lambda: phone.say(text, audio), None, timings, "phone")
        await send({"type": "say", "text": text, "audio": base64.b64encode(audio).decode() if audio else None, "emotion": mood})
        said_at.append(f"{text!r} {time.perf_counter() - begin:.1f}s {mood}" + (f" x{hurry:.2f}" if hurry > 1 else ""))

    try:
        while not hold["stopped"] and (not hold["times"] or hold["times"][-1] - hold["times"][0] < MAX_HOLD):
            if looking and looking.done():
                now_seen = looking.result()
                if feeling is None or now_seen == seen:  # a change needs two looks in a row: no flicker
                    feeling = now_seen
                seen, looking = now_seen, None
            if not looking and hold["frames"] and time.perf_counter() - looked_at > FACE_EVERY:
                looked_at = time.perf_counter()
                looking = asyncio.create_task(asyncio.to_thread(safe, look, feeling or "neutral", timings, "emotion"))
            if not streaming.due(hold):
                await asyncio.sleep(0.02)
                continue
            result = await asyncio.to_thread(safe, lambda: streaming.step(hold), None, timings, "read")
            reads.append(timings["read"])
            if result:
                await send({"type": "heard", "heard": result["heard"], "pending": result["pending"], "face": result["face"]})
                if result["say"]:
                    voicing = asyncio.create_task(voice(result["say"], voicing))
        released = time.perf_counter() - begin
        words = await asyncio.to_thread(safe, lambda: streaming.finish(hold), [], timings, "last read")
        if words:
            voicing = asyncio.create_task(voice(words, voicing))
        if voicing:
            await voicing
        text = " ".join(hold["spoken"])
        if text:
            history.append({"speaker": "me", "text": text})
        await send({"type": "done", "text": text, "emotion": feeling or "neutral"})
        last = f"last words voiced {time.perf_counter() - begin - released:.2f}s after release" if words else "nothing left at release"
        mean = round(sum(reads) / len(reads)) if reads else None
        print(f"live: {', '.join(said_at) or 'nothing read'} | released at {released:.1f}s, {last} | {len(reads)} readings, "
              f"ms: read {mean} (max {max(reads, default=None)}), last read {timings.get('last read')}, "
              f"tts {timings.get('tts')}, face {timings.get('emotion')}", flush=True)
        if hold["frames"]:  # keep it, like the recorded clips: test material for lip reading
            RECORDINGS.mkdir(exist_ok=True)
            path = RECORDINGS / f"{time.strftime('%Y%m%d-%H%M%S')}-live.mp4"
            meanwhile.submit(safe, lambda: streaming.save(hold, path), None, {}, "save")
    except Exception:
        traceback.print_exc()
        try:
            await send({"type": "error", "message": "Something went wrong while reading: see the server's terminal."})
        except Exception:  # the phone is gone
            pass


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
