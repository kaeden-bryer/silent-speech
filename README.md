# Silent Speech

For people who can move their lips but can't make a sound: hold up your phone, mouth a sentence, and the phone says it out loud.

```
 browser (frontend/)                 backend (backend/app/)
 ───────────────────                 ─────────────────────────────────────────────────
 camera ── video clip ─────────────▶ lipreading ─┬─▶ correction ─┬─▶ tts ──▶ audio
                                                 └─▶ emotion ────┘            │
 speaker ◀── audio (or browser voice) ◀───────────────────────────────────────┤
                                                    telephony (during a call) ◀┘
```

## Who does what

| Track | Builds | Folder | Contract |
|---|---|---|---|
| 1. Frontend | The web app: camera, recording, playback, call UI | [frontend/](frontend/) | HTTP API below, in [api.js](frontend/js/api.js) |
| 2. Lip reading | Video → text (e.g. Auto-AVSR) | [lipreading/](backend/app/modules/lipreading/) | `LipReader` |
| 3. Voice | LLM text correction + realistic TTS | [correction/](backend/app/modules/correction/), [tts/](backend/app/modules/tts/) | `TextCorrector`, `TTSEngine` |
| 4. Extras | Emotion → tone of voice, phone calls | [emotion/](backend/app/modules/emotion/), [telephony/](backend/app/modules/telephony/) | `EmotionDetector`, `Telephony` |

Each module folder has a `base.py` (the abstract class you implement) and a README with the details.

## Every part has a placeholder

Each module ships with a placeholder implementation. If your part isn't written, isn't configured or crashes, the app uses the placeholder and everything else keeps working.

| Module | Placeholder | What it does |
|---|---|---|
| lipreading | `mock` | Ignores the video, returns noisy sample sentences |
| correction | `passthrough` | Returns the text unchanged |
| emotion | `neutral` | Always neutral |
| tts | `browser` | Returns no audio; the frontend speaks with the device's voice |
| telephony | `disabled` | Call endpoints answer 503 |

- **At startup:** if the implementation selected in `.env` is missing or raises in `load()`, the placeholder is used. `/api/health` shows the reason.
- **Per request:** if an implementation raises, the placeholder handles that request and the error appears in the response's `stages`. Lip reading is the exception: it returns empty text instead of a mock sentence, so the app never speaks words the user didn't say.

## Run it

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env             # macOS/Linux: cp .env.example .env
uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

- http://localhost:8000: the frontend (a bare test page for now)
- http://localhost:8000/docs: interactive API docs, handy for testing the backend without a frontend
- http://localhost:8000/api/health: which implementation each module runs
- `pytest` (in `backend/`): end-to-end tests with every placeholder. CI runs them on every push.

### Test on your phone

Phone browsers only allow the camera over HTTPS. Expose your backend with a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000   # no account needed, prints an https://….trycloudflare.com URL
# or: ngrok http 8000
```

Open the printed URL on your phone. Telephony needs a public URL like this anyway, for its webhooks.

## Adding your implementation (tracks 2–4)

1. Create a file in your module folder with a class that implements the abstract class in `base.py`. Do your setup in `load()` (load the model, read API keys with `os.getenv`) and raise there if it can't work.
2. Register it in your module's `__init__.py`, e.g. `"auto_avsr": ".auto_avsr:AutoAVSRLipReader"`.
3. Select it in your `.env`, e.g. `LIPREADING=auto_avsr`.
4. Test it alone, without the server: `python -m app.modules.lipreading clip.webm` (each module has one, see its README). Then test it in the app.

Your extra Python packages go in a `requirements.txt` inside your module folder, not in `backend/requirements.txt`, so nobody has to install torch just to run the app. Add your env var names (empty) to `.env.example`.

## Ground rules

- Work in your own folder, on your own branch (`track/lipreading`, …). Open PRs into `main` and keep CI green.
- These files are the contract between tracks: `backend/app/schemas.py`, the `base.py` files, `backend/app/pipeline.py`, `backend/app/api.py`, `frontend/js/api.js`. Tell the team before changing them. Adding an optional field is safe; renaming or removing one breaks someone else's code.
- Never commit `.env`, model weights (`backend/models/`) or cloned repos (`backend/third_party/`). They are gitignored.

## HTTP API (frontend ↔ backend)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/health` | | `{ok, modules: [{kind, requested, active, fallback, error}]}` |
| POST | `/api/utterance/video` | multipart: `session_id`, `video` (one sentence, webm/mp4) | `UtteranceResult` |
| POST | `/api/utterance/text` | `{session_id, text, correct: true}` | `UtteranceResult` |
| GET | `/api/audio/{id}` | | audio bytes |
| GET | `/api/session/{id}` | | `{session_id, turns: [{speaker, text, timestamp}], call_active}` |
| POST | `/api/session/{id}/reset` | | `{ok}` |
| POST | `/api/call/start` | `{session_id, to}` | `{call_id}`, or 503 if telephony is unavailable |
| POST | `/api/call/hangup` | `{session_id}` | `{ok}` |

`/api/utterance/text` treats typed text as lip reader output. It lets you test correction, emotion, TTS and calls without lip reading.

```jsonc
// UtteranceResult
{
  "session_id": "…",
  "raw_text": "can i half a coffee wiz oat milk",   // from the lip reader (or typed)
  "text": "Can I have a coffee with oat milk?",     // corrected: what gets spoken ("" = nothing understood)
  "emotion": {"label": "happy", "intensity": 0.6},
  "audio_url": "/api/audio/3f2a…",                  // null = speak `text` with the browser voice
  "stages": [{"stage": "correction", "impl": "passthrough", "ms": 412.0, "error": null}],
  "total_ms": 980.0
}
```

All types are defined in [backend/app/schemas.py](backend/app/schemas.py).

## Repo layout

```
frontend/                   track 1 (bare test page for now)
  js/api.js                 every backend call: the frontend contract
backend/
  app/
    schemas.py              shared data types: the backend contract
    pipeline.py             runs one utterance through the modules, handles fallbacks
    api.py                  HTTP endpoints
    loader.py               picks implementations from .env, falls back to placeholders
    main.py                 app factory
    modules/
      lipreading/           track 2
      correction/  tts/     track 3
      emotion/  telephony/  track 4
  tests/                    end-to-end tests with placeholders
```
