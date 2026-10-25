"""Track 4: real phone calls through Twilio.

server.py calls start_call() when the user presses "Call", say() after every
sentence while the call is on, and hang_up() when they press "Hang up".
active() tells it when the other person hung up.

How: Twilio dials the number. When they answer, Twilio opens a WebSocket to /ws/twilio
(through the Cloudflare tunnel, see PUBLIC_HOST) and streams the call both ways as
8 kHz mu-law. say() sends our Kokoro voice down it. What the other person says is cut
into sentences (a simple loudness check) and turned into text by stt.py; it goes into
`history`: the website shows it as captions and the corrections use it as context.
Their voice is also passed on live, 100 ms at a time, to the app's call screen
(/api/call/audio), so the user hears them too. Only with the call's own key: the tunnel is public.

Keys in backend/.env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER (+15551234567).
Needs the internet (the tunnel + Twilio); everything else in the app still works without it.
"""

import asyncio
import base64
import io
import json
import os
import secrets
import traceback
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from scipy.signal import resample_poly
from twilio.request_validator import RequestValidator
from twilio.rest import Client

try:
    import stt  # captions of the other person. Without it the call still works, just no captions
except Exception:
    traceback.print_exc()
    stt = None

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "app.silent-speech.us")  # the Cloudflare tunnel to this server
RATE = 8000  # phone audio
FRAME = 160  # 20 ms at 8 kHz, what Twilio sends and expects
SPEECH = 500  # loudness (RMS of 16-bit samples) above which a frame counts as speech
PAUSE = 30  # frames of quiet (600 ms) that end a sentence
LONGEST = 750  # frames (15 s): cut a sentence here even if they keep talking
LEAD_IN = 10  # frames kept from before the speech started, so the first sound isn't cut off
PASS_ON = 5  # frames (100 ms) of their voice sent to the app at a time

router = APIRouter()
history = []  # the list from server.py, given to start_call
call = {}  # the current call: sid, token, listen key, and once answered: ws, loop, stream
captions = ThreadPoolExecutor(1)  # one at a time, so captions stay in order
ears = set()  # the app's call screens hearing the other person live


def start_call(number: str, history_list: list[dict]) -> None:
    global history
    sid, token, own = (os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_NUMBER"))
    if not (sid and token and own):
        raise RuntimeError("Calls aren't set up: add the TWILIO_* keys to backend/.env")
    if call:
        hang_up()
    history = history_list
    secret = secrets.token_urlsafe(16)  # only the stream Twilio opens for this call is accepted
    twiml = (
        f'<Response><Connect><Stream url="wss://{PUBLIC_HOST}/ws/twilio">'
        f'<Parameter name="secret" value="{secret}"/></Stream></Connect></Response>'
    )
    placed = Client(sid, token).calls.create(
        to=number,
        from_=own,
        twiml=twiml,
        status_callback=f"https://{PUBLIC_HOST}/twilio/status",
        status_callback_event=["completed"],
    )
    call.update(sid=placed.sid, secret=secret, listen=secrets.token_urlsafe(16))
    print(f"Calling {number} ({placed.sid})", flush=True)


def listen_key() -> str | None:
    """The key the app's call screen needs to hear the other person (given to whoever dialed)."""
    return call.get("listen")


def say(text: str, audio: bytes | None) -> None:
    if "ws" not in call:
        raise RuntimeError(f"not said, nobody has answered yet: {text!r}")
    if audio is None:  # no Kokoro: nothing to play (Twilio's own voice would end the stream)
        raise RuntimeError(f"not said, no audio: {text!r}")
    samples, rate = sf.read(io.BytesIO(audio), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    sound = to_mulaw(resample_poly(samples, RATE, rate))
    asyncio.run_coroutine_threadsafe(send(call["ws"], call["stream"], sound), call["loop"]).result(timeout=10)


def hang_up() -> None:
    sid = call.get("sid")
    call.clear()
    if sid:
        Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")).calls(sid).update(status="completed")


def active() -> bool:
    return "sid" in call


async def send(ws, stream, sound):
    for i in range(0, len(sound), FRAME):
        payload = base64.b64encode(sound[i : i + FRAME]).decode()
        await ws.send_text(json.dumps({"event": "media", "streamSid": stream, "media": {"payload": payload}}))


@router.websocket("/ws/twilio")
async def media_stream(ws: WebSocket):
    """Twilio's side of the call: the other person's voice in, ours out."""
    await ws.accept()
    listener = Listener()
    heard = bytearray()  # their voice not yet passed on to the app
    try:
        async for message in ws.iter_text():
            event = json.loads(message)
            if event["event"] == "start":
                start = event["start"]
                if start.get("customParameters", {}).get("secret") != call.get("secret"):
                    print("Refused a media stream that isn't our call", flush=True)
                    return await ws.close()
                call.update(ws=ws, loop=asyncio.get_running_loop(), stream=start["streamSid"])
                print("Call answered", flush=True)
            elif event["event"] == "media" and "ws" in call:
                chunk = base64.b64decode(event["media"]["payload"])
                listener.hear(chunk)
                heard += chunk
                if len(heard) >= PASS_ON * FRAME:
                    await pass_on(bytes(heard))
                    heard.clear()
            elif event["event"] == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        listener.flush()
        if call.get("ws") is ws:
            call.clear()
            print("Call ended", flush=True)


async def pass_on(sound):
    for ear in list(ears):
        try:
            await ear.send_bytes(sound)
        except Exception:  # that screen is gone
            ears.discard(ear)


@router.websocket("/api/call/audio")
async def call_audio(ws: WebSocket, key: str = ""):
    """The other person's voice, live, for the app's call screen: 8 kHz mu-law, 100 ms at a time."""
    await ws.accept()
    if not key or key != call.get("listen"):
        return await ws.close(code=4403)  # not the one who dialed this call
    ears.add(ws)
    try:
        while True:
            await ws.receive_text()  # nothing comes this way: this just waits until the screen goes away
    except WebSocketDisconnect:
        pass
    finally:
        ears.discard(ws)


@router.post("/twilio/status")
async def call_status(request: Request):
    """Twilio tells us the call is over: unanswered, busy, or they hung up."""
    form = dict(await request.form())
    signed = RequestValidator(os.getenv("TWILIO_AUTH_TOKEN", "")).validate(
        f"https://{PUBLIC_HOST}/twilio/status", form, request.headers.get("X-Twilio-Signature", "")
    )
    if not signed:  # the URL is public: only Twilio may end our call
        return Response(status_code=403)
    if form.get("CallSid") == call.get("sid"):
        print(f"Call {form.get('CallStatus')}", flush=True)
        call.clear()
    return Response(status_code=204)


class Listener:
    """Cuts the other person's audio into sentences and sends each one to stt.py."""

    def __init__(self):
        self.frames, self.quiet, self.talking = [], 0, False

    def hear(self, chunk):
        frame = from_mulaw(chunk)
        loud = np.sqrt(np.mean(frame.astype(np.float32) ** 2)) > SPEECH
        self.frames.append(frame)
        if not self.talking:
            self.talking = loud
            self.frames = self.frames[-LEAD_IN:]
        elif loud:
            self.quiet = 0
        else:
            self.quiet += 1
        if self.talking and (self.quiet >= PAUSE or len(self.frames) >= LONGEST):
            self.flush()

    def flush(self):
        if self.talking and stt:
            captions.submit(caption, np.concatenate(self.frames))
        self.frames, self.quiet, self.talking = [], 0, False


def caption(samples):
    try:
        text = stt.transcribe(resample_poly(samples / 32768, stt.SAMPLE_RATE, RATE).astype(np.float32))
    except Exception:
        traceback.print_exc()
        return
    if text:
        history.append({"speaker": "them", "text": text})
        print(f"them: {text!r}", flush=True)


# G.711 mu-law, the phone network's 8-bit audio (Python 3.13 removed audioop)
BIAS, CLIP = 0x84, 32635


def to_mulaw(samples):
    pcm = np.clip(samples * 32767, -32768, 32767).astype(np.int32)
    sign = (pcm < 0).astype(np.int32) << 7
    pcm = np.minimum(np.abs(pcm), CLIP) + BIAS
    exponent = np.floor(np.log2(pcm)).astype(np.int32) - 7
    mantissa = (pcm >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


def _decode(byte):
    byte = ~byte & 0xFF
    pcm = ((((byte & 0x0F) << 3) + BIAS) << ((byte >> 4) & 0x07)) - BIAS
    return -pcm if byte & 0x80 else pcm


MULAW = np.array([_decode(b) for b in range(256)], dtype=np.int16)


def from_mulaw(chunk):
    return MULAW[np.frombuffer(chunk, dtype=np.uint8)]
