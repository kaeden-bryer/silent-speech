# Silent Speech

For people who can move their lips but can't make a sound: hold up your phone, hold the button, mouth a sentence, and the phone says it out loud, word by word, while you are still mouthing.

**camera → live lip reading → emotion → voice → speaker (or phone call)**

## Who does what

Everyone works in their own file. Each file has one function that returns a fake answer, so the whole app already runs. Replace the fake answer with the real thing.

| Track | File | Function |
|---|---|---|
| 1. Website | `frontend/index.html` | the page: camera, recording, playing the voice |
| 2. Lip reading | `backend/lipreading.py` | `lip_read(video_path)` → text |
| 2. Live lip reading | `backend/streaming.py` | `step(hold)` → the words that are sure while the user is still mouthing (uses `lipreading.py`'s model). Try it: `python streaming.py clip.webm` |
| 3. Correction | `backend/llm_correction.py` | `llm_correct(raw_text, history)` → fixed text, by a local LLM using the conversation. **Off** (`LLM_CORRECTION` in `server.py`): it rewrites whole sentences, live mode speaks word by word |
| 3. Correction | `backend/correction.py` | `correct(raw_text, history)` → fixed text |
| 3. Voice | `backend/tts.py` | `text_to_speech(text, emotion)` → MP3 bytes, or `None` for the browser voice. The fallback for the one below |
| 3. Emotional voice | `backend/emotional_tts.py` | `text_to_speech(text, emotion, hurry)` → (WAV bytes, seconds): Kokoro in ~30 ms, with its pitch curve bent per emotion and no silence around it. Hear it: `python emotional_tts.py "hello there"` |
| 4. Emotion | `backend/emotion.py` | `detect_emotion(video_path, text)` → `"neutral"`, `"energetic"`, `"sad"` or `"angry"` |
| 4. Phone calls | `backend/phone.py` | `start_call`, `say`, `hang_up`, `active`: real calls through Twilio |
| 4. Call captions | `backend/stt.py` | `transcribe(audio)` → what the other person on the call said (local Whisper) |

`backend/server.py` connects everything. If your function crashes, or your file doesn't even import, the server prints the error and uses a safe default instead: the raw text, `"neutral"`, the browser's voice… One broken part never breaks the demo.

## Run

Lip reading, voice and correction run locally on the Ascent GPU. One-time setup (models, CUDA torch): [`models/MANIFEST.md`](models/MANIFEST.md). Test the lip reader alone with `python lipreading.py clip.webm`. Demo phrases live in `backend/demo_phrases.txt`.

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

- Open http://localhost:8000.
- After pulling, rebuild the website: `cd frontend && npm install && npm run build`. `frontend/dist` is not in git, so a pull alone doesn't change what the phone sees.
- Every sentence prints one line in the terminal with how long each step took (`ms: lip 459, emotion 85, llm 553, snap 0, tts 50`).
- Typing a sentence works as if the lip reader had read it, so you can test your part without the camera.
- API keys go in `backend/.env` (never commit it). Read them with `os.getenv("NAME")`.
- Packages you need go in `backend/requirements.txt`.
- Every recorded clip is saved in `backend/recordings/`: test material for lip reading.

**On your phone:** phones only allow the camera over HTTPS. With no internet, use the Ascent's own Wi-Fi and certificate: [`offline-demo-instructions.md`](offline-demo-instructions.md). With internet, run `python server.py` and `cloudflared tunnel run` on the Ascent and open https://app.silent-speech.us (our named tunnel, `~/.cloudflared/config.yml` on the Ascent).

**Phone calls** need the internet and the tunnel (Twilio connects to `app.silent-speech.us`). Put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_NUMBER` (`+15551234567`) in `backend/.env`. Use an upgraded Twilio account: a trial one can only call verified numbers and plays a "press any key" message first. Steps: the "Phone calls" section of [`offline-demo-instructions.md`](offline-demo-instructions.md).

## API (for the website)

| Request | Send | Get back |
|---|---|---|
| `WebSocket /api/live` | `{"type": "start", "voice": "am_michael"}`, then frames (8-byte time in ms, float64 little-endian, + one JPEG), then `{"type": "stop"}` | `{"type": "heard", "heard", "pending", "face"}` after each reading, `{"type": "say", "text", "audio", "emotion"}` for each group of sure words (in order; the emotion follows the face), `{"type": "done", "text", "emotion"}` |
| `POST /api/video` | form field `video`: the recorded clip | result |
| `POST /api/text` | `{"text": "...", "voice": "am_michael"}` (voice optional) | result |
| `GET /api/history` | | `{"history": [{"speaker": "me" or "them", "text": "..."}], "call_active": true/false}` |
| `POST /api/call` | `{"number": "+15551234567"}` | `{"ok": true}`, or an error if calls aren't set up |
| `POST /api/hangup` | | `{"ok": true}` |

Twilio's routes (not for the website): `wss://app.silent-speech.us/ws/twilio` carries the call audio both ways (8 kHz mu-law), and `POST /twilio/status` tells us when the call is over. `call_active` turns `false` on its own when the other person hangs up.

The result looks like this:

```json
{"raw_text": "helo how r you", "text": "Hello, how are you?", "emotion": "energetic", "audio": "<base64 WAV (or MP3) or null>"}
```

If `audio` is `null`, read `text` aloud with the browser's own voice.
