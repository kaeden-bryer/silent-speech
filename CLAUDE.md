# Silent Speech

**Phone/laptop camera → lip reading → correction → emotion → TTS → speaker**, all inference local on an ASUS Ascent GX10.

A user silently mouths a short sentence; the browser records the clip, uploads it to the Ascent, and plays back the synthesized speech. "Lip-sync → TTS" means *lip reading → TTS* (video in, audio out), not Wav2Lip-style talking faces.

## Where things are documented

| Topic | File |
|---|---|
| Team tracks, API shapes, dev run | `README.md` |
| Model checkpoints, versions, setup gotchas | `models/MANIFEST.md` |
| Offline demo (hotspot + HTTPS certs + iPhone) | `offline-demo-instructions.md` |
| Frontend structure and dev server | `frontend/README.md` |
| Not-yet-built features / wishlist | `FEATURES.md` |

Don't duplicate those here; update them when the thing they describe changes.

## Architecture

- **Frontend** (`frontend/`): Vite + React 19 + Tailwind 4. Screens in `src/screens/`, camera + clip recording in `src/useClipRecorder.js` (LiveCapture is home; Conversation is the Call screen), all backend calls in `src/api.js`, persisted settings in `src/settings.js`. Tap toggles recording; the whole clip goes up via `POST /api/video`. `test.html` is a bare pipeline test page. `npm run design-review` runs the Playwright/axe harness.
- **Backend** (`backend/server.py`, FastAPI): `lipreading.py` (Auto-AVSR + MediaPipe Tasks FaceDetector) → `llm_correction.py` (Qwen3-4B, lip-lookalike edits only) → `correction.py` (rapidfuzz snap to `demo_phrases.txt`, threshold 70) → `emotion.py` (FER2013 mini-Xception ONNX via `cv2.dnn`, returns `neutral`/`energetic`/`sad`/`angry`) → `tts.py` (Kokoro `af_heart`, MP3, speed nudged by emotion). `phone.py` places real calls via Twilio Media Streams over the `app.silent-speech.us` Cloudflare tunnel (the one part that needs internet); `stt.py` (Whisper) captions the other side into `history`.
- `server.py` serves `frontend/dist` (or `frontend/` if unbuilt) at `/`. `python server.py` serves HTTPS when `certs/server.pem` + `server.key` exist (made by `scripts/setup_network.sh certs`); otherwise plain HTTP. Phones need HTTPS for the camera.
- Every uploaded clip is saved to `backend/recordings/` (test material).

## Conventions

- **Never let one stage break the demo.** `server.py` imports each module with `load()` and runs each step with `safe(step, fallback)`; a crash prints the traceback and falls back (raw text, `"neutral"`, `audio: null` → browser voice). Keep new stages behind the same pattern.
- No config file: settings are constants at the top of each backend file.
- Models load and warm up at import; a lock per model serializes GPU/`cv2.dnn` use.
- If lip reading returns nothing, return empty text and say nothing rather than guessing.
- Comments are short and explain *why*; match the plain style of the existing files.

## Platform: GX10 (aarch64 + Blackwell sm_121, CUDA 13)

- Use PyTorch `cu130` aarch64 wheels. pip checks versions, not CUDA ABI: install one package at a time, import it, and never let a later install replace the `+cu130` torch (use `--no-deps`).
- Verify GPU with a real kernel (`x @ x` then `torch.cuda.synchronize()`), not just `is_available()`. `sm_120` without `sm_121` in the arch list is fine.
- Avoid `flash-attn` and PyPI `onnxruntime-gpu` (no aarch64 + CUDA 13 wheels).
- Don't run Auto-AVSR's `requirements.txt` blindly; it may pin an incompatible torch.
- Fallback if the venv breaks: NGC container `nvcr.io/nvidia/pytorch:26.01-py3` with `--gpus all --net=host --ipc=host` (pull it while online).
- Offline: `HF_HUB_OFFLINE=1` once Kokoro is cached. Weights in `models/`, Auto-AVSR in `third_party/` (both gitignored).

## Accuracy expectations

Open-vocabulary lip reading is ~20–30 % WER on benchmarks and worse on new faces/lighting. The demo relies on short phrases (3–8 words), frontal face, even light, and the phrase-snapping safety net. Preprocessing must match Auto-AVSR's own transforms exactly, or accuracy silently collapses. First request after startup is slower (CUDA init); do a dry run before judges.
