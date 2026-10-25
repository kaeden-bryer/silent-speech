# Silent Speech

For people who can move their lips but can't make a sound: hold up your phone, mouth a sentence, and the phone says it out loud.

**camera → lip reading → correction → emotion → voice → speaker (or phone call)**

## Who does what

Everyone works in their own file. Each file has one function that returns a fake answer, so the whole app already runs. Replace the fake answer with the real thing.

| Track | File | Function |
|---|---|---|
| 1. Website | `frontend/index.html` | the page: camera, recording, playing the voice |
| 2. Lip reading | `backend/lipreading.py` | `lip_read(video_path)` → text |
| 3. Correction | `backend/llm_correction.py` | `llm_correct(raw_text, history)` → fixed text, by a local LLM using the conversation. Runs first |
| 3. Correction | `backend/correction.py` | `correct(raw_text, history)` → fixed text |
| 3. Voice | `backend/tts.py` | `text_to_speech(text, emotion)` → MP3 bytes, or `None` for the browser voice |
| 4. Emotion | `backend/emotion.py` | `detect_emotion(video_path, text)` → `"neutral"`, `"energetic"`, `"sad"` or `"angry"` |
| 4. Phone calls | `backend/phone.py` | `start_call`, `say`, `hang_up` |

`backend/server.py` connects everything. If your function crashes, or your file doesn't even import, the server prints the error and uses a safe default instead: the raw text, `"neutral"`, the browser's voice… One broken part never breaks the demo.

## Run

Lip reading, voice and correction run locally on the Ascent GPU. One-time setup (models, CUDA torch): [`models/MANIFEST.md`](models/MANIFEST.md). Test the lip reader alone with `python lipreading.py clip.webm`. Demo phrases live in `backend/demo_phrases.txt`.

```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

- Open http://localhost:8000.
- Typing a sentence works as if the lip reader had read it, so you can test your part without the camera.
- API keys go in `backend/.env` (never commit it). Read them with `os.getenv("NAME")`.
- Packages you need go in `backend/requirements.txt`.
- Every recorded clip is saved in `backend/recordings/`: test material for lip reading.

**On your phone:** phones only allow the camera over HTTPS. Run `cloudflared tunnel --url http://localhost:8000` and open the `https://` URL it prints.

## API (for the website)

| Request | Send | Get back |
|---|---|---|
| `POST /api/video` | form field `video`: the recorded clip | result |
| `POST /api/text` | `{"text": "..."}` | result |
| `GET /api/history` | | `{"history": [{"speaker": "me" or "them", "text": "..."}], "call_active": true/false}` |
| `POST /api/call` | `{"number": "+15551234567"}` | `{"ok": true}`, or an error if calls aren't set up |
| `POST /api/hangup` | | `{"ok": true}` |

The result looks like this:

```json
{"raw_text": "helo how r you", "text": "Hello, how are you?", "emotion": "energetic", "audio": "<base64 MP3 or null>"}
```

If `audio` is `null`, read `text` aloud with the browser's own voice.
