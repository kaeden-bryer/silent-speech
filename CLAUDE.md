# Silent-Speech Pipeline: Specification

**Webcam lip movements (MacBook) → lip reading + TTS (ASUS Ascent GX10) → synthesized speech (MacBook speaker)**

Status: draft v0.1

---

## 1. Overview

A person silently mouths a sentence in front of the MacBook webcam. The video is streamed to the Ascent, which:

1. finds the mouth region in each frame,
2. runs a **visual speech recognition (VSR)** model to turn lip motion into text,
3. runs a **TTS** model to turn that text into audio,
4. returns the audio to the MacBook, which plays it on its speaker.

> **Interpretation note.** "Lip-sync → TTS" is read here as *lip reading → TTS* (video in, audio out). Models like Wav2Lip and MuseTalk go the opposite direction (audio → talking-face video) and are **not** used. If the intent was different, this spec needs revisiting.

### Goals
- All inference runs locally on the Ascent. The MacBook is a thin I/O client.
- The demo works with **no internet** (direct Ethernet cable between the two machines).
- Push-to-talk interaction that is predictable on a judging table.
- End-to-end latency from key release to first audio: **target < 2 s** (to be measured, see §10).

### Non-goals (v1)
- Continuous, always-on streaming recognition.
- Multi-speaker or multi-language support.
- Voice cloning.
- Running any model on the MacBook.

---

## 2. Architecture

```
MacBook (client)                                  ASUS Ascent GX10 (server)
────────────────                                  ─────────────────────────
webcam (25 fps)                                   WebSocket endpoint /stream
  │                                                 │
  ▼                                                 ▼
preview window + SPACE push-to-talk               frame buffer (per utterance)
  │ JPEG frames while SPACE held                    │
  └──────── WebSocket over Ethernet ───────────►    ▼
                                                  mouth-ROI extraction (MediaPipe)
                                                    │  96×96 grayscale crops
                                                    ▼
                                                VSR model (Auto-AVSR)  → text
                                                    │
                                                    ▼
                                                  TTS model (Kokoro-82M) → PCM audio
                                                    │
speaker  ◄── sounddevice stream ◄────────────────────┘  JSON transcript + binary audio chunks
```

**Why push-to-talk:** lip-reading models are trained on *whole utterances* (a few seconds of video), not an endless stream. Something has to decide where an utterance starts and ends. Voice-activity detection is impossible here (there is no audio input), and mouth-motion detection is fiddly. A key held down is deterministic, so it's the right v1 choice. Automatic endpointing is a stretch goal (§12).

**Why the server does ROI extraction:** it keeps the client trivial and avoids duplicating dependencies. If bandwidth or latency becomes an issue, move cropping to the Mac and send only 96×96 crops (≈100× fewer pixels).

---

## 3. Models

| Stage | Primary | Why | Fallback |
|---|---|---|---|
| Face/mouth landmarks | **MediaPipe Face Mesh** | Fast, CPU-capable, gives lip landmarks for cropping | RetinaFace / face-alignment (used by the Auto-AVSR repo's own preprocessing) |
| Visual speech recognition | **Auto-AVSR** (`mpc001/auto_avsr`), pretrained **VSR** checkpoint (trained on LRS3, optionally with additional datasets) | Best-known open pretrained lip-reading model; Conformer encoder + hybrid CTC/attention decoding | `mpc001/Visual_Speech_Recognition_for_Multiple_Languages` (predecessor, same authors) |
| TTS | **Kokoro-82M** (`hexgrad/Kokoro-82M`, Apache-2.0) | Tiny (82M params), fast, natural, easy pip install, 24 kHz output | **Piper** (CPU, very robust) |
| Constrained matcher (safety net) | `rapidfuzz` fuzzy match of VSR output against a list of demo phrases | Lip reading is error-prone on open vocabulary; snapping to a known phrase list makes the demo reliable | Disable via config |

> Checkpoint filenames and download links change between releases. Take them from each repository's README at setup time and record the exact versions you used in `models/MANIFEST.md`.

### Expectations on accuracy (read this)
Open-vocabulary lip reading is hard. Published word error rates on LRS3 benchmark data are around 20–30 %, and performance on an unfamiliar face, lighting, and camera angle in a hackathon venue will be **worse**. Plan the demo around this:
- Keep utterances short (3–8 words), frontal face, good even lighting, camera at mouth height.
- Use the phrase-matching safety net (`demo_phrases.txt`) for the judged demo.
- Show the raw transcript on screen so judges see what was recognized.

---

## 4. Wire Protocol

Single WebSocket at `ws://<server>:8000/stream`. Text messages are JSON control messages. Binary messages are payloads.

### Client → Server
| Kind | Format | Meaning |
|---|---|---|
| Text | `{"type":"start","fps":25}` | Begin utterance (SPACE pressed) |
| Binary | JPEG bytes | One video frame (sent while SPACE is held) |
| Text | `{"type":"end"}` | End utterance (SPACE released), triggers inference |

### Server → Client
| Kind | Format | Meaning |
|---|---|---|
| Text | `{"type":"transcript","text":"...","raw":"...","matched":true}` | Recognized text (`raw` = model output, `text` = after phrase matching) |
| Binary | PCM, signed 16-bit little-endian, mono, 24000 Hz | Audio chunk, played as it arrives |
| Text | `{"type":"done","timings":{"roi_ms":..,"vsr_ms":..,"tts_ms":..}}` | Utterance complete |
| Text | `{"type":"error","message":"..."}` | Failure (client shows it and stays connected) |

**Why this shape:** the client sends frames *without waiting for replies*, and the server answers only after `end`. That removes the lockstep stutter of a send-then-wait loop. Audio is sent in chunks so playback can begin before the whole sentence is synthesized (Kokoro yields audio per sentence/segment).

---

## 5. Server Specification (Ascent)

### 5.1 Responsibilities
- Accept one client connection (a second connection replaces the first).
- Buffer frames per utterance; ignore utterances shorter than `min_frames`.
- Run ROI → VSR → (optional phrase match) → TTS; stream results back.
- Load all models **once at startup** and run a **warm-up inference** before accepting connections.

### 5.2 Processing steps per utterance
1. **Decode** JPEGs to BGR arrays (`cv2.imdecode`).
2. **Landmarks**: MediaPipe Face Mesh per frame; take the outer-lip landmarks; compute a bounding box.
3. **Smooth** the box across frames (moving average) so the crop doesn't jitter. Jitter looks like fake mouth motion to the model.
4. **Crop** a square region around the mouth, resize to 96×96, convert to grayscale, normalize as the Auto-AVSR preprocessing expects (follow the repo's `preparation`/`datamodule` transforms exactly; a mismatch here silently ruins accuracy).
5. **Frames with no detected face**: reuse the previous box; if more than `max_missing_frac` are missing, return an error ("face not found").
6. **VSR inference** on the crop sequence → text (lowercased, stripped).
7. **Phrase match** (if enabled): best `rapidfuzz` match ≥ `match_threshold` replaces the text.
8. **TTS**: Kokoro generates audio; convert float32 → int16 PCM; send each chunk as it is produced.

### 5.3 Concurrency
- WebSocket handler is `async`; all GPU/CPU-heavy work goes through `asyncio.to_thread` (or a single-worker executor) so the event loop keeps answering pings.
- Process **one utterance at a time**. A GPU lock serializes inference.

### 5.4 Failure behavior
Every failure path sends an `error` message and returns to idle. The server must never crash on bad input (empty utterance, undecodable JPEG, no face).

---

## 6. Client Specification (MacBook)

### 6.1 Responsibilities
- Open the webcam (OpenCV, 640×480 @ 25 fps; the VSR models are trained on 25 fps video).
- Show a preview window with status text (connected / recording / processing) and the last transcript.
- **SPACE held = recording.** On press send `start`; while held, send JPEG frames (quality 80); on release send `end`.
- Play received PCM on the default output device.
- Reconnect automatically if the socket drops.

### 6.2 Key handling
Use `cv2.waitKey` in the preview window rather than a global key listener such as `pynput`. A global listener needs macOS Accessibility/Input Monitoring permission, which is an easy thing to forget before a demo. `waitKey` has no extra permissions. Because `waitKey` reports key *presses* and not releases, implement SPACE as a **toggle** (press to start, press again to stop) or a **hold detected by key-repeat timing**. Toggle is the simplest and most reliable, and is the v1 behavior.

### 6.3 Audio playback
Use `sounddevice.RawOutputStream(samplerate=24000, channels=1, dtype="int16")`. Write chunks as they arrive. Keep the stream open for the whole session so there is no device-open delay on first playback.

---

## 7. Configuration

Both sides read `config.yaml` (env vars override). Keep one file in the repo root and edit the `server`/`client` sections for each machine.

```yaml
network:
  server_host: "192.168.77.2"   # demo: cable IP.  dev: Tailscale name/IP
  server_port: 8000

client:
  camera_index: 0
  fps: 25
  width: 640
  height: 480
  jpeg_quality: 80
  toggle_key: " "               # space
  audio_samplerate: 24000

server:
  bind_host: "0.0.0.0"
  device: "cuda"
  min_frames: 10                # ignore utterances shorter than ~0.4 s
  max_missing_frac: 0.3
  vsr:
    repo_path: "third_party/auto_avsr"
    checkpoint: "models/vsr_checkpoint.pth"   # exact name from the repo README
    beam_size: 10
  tts:
    engine: "kokoro"
    voice: "af_heart"
    speed: 1.0
  phrases:
    enabled: true
    file: "demo_phrases.txt"
    match_threshold: 70         # rapidfuzz score, 0-100
```

---

## 8. Setup: ASUS Ascent GX10 (server)

The GX10 is an NVIDIA GB10 (Grace Blackwell) system: **aarch64 CPU + Blackwell GPU**, running NVIDIA's DGX OS (Ubuntu-based). The aarch64 part matters. Many pip wheels that "just work" on x86 either don't exist or lack CUDA support on ARM, which is why the recommended path below uses NVIDIA's prebuilt container.

### 8.1 Base environment (recommended: NGC PyTorch container)
```bash
# Pull NVIDIA's PyTorch container (pick the current tag from NGC / the GX10 docs)
docker pull nvcr.io/nvidia/pytorch:<TAG>

docker run --gpus all -it --rm --net=host --ipc=host \
  -v $PWD:/workspace/app -w /workspace/app \
  nvcr.io/nvidia/pytorch:<TAG> bash
```
- `--net=host` exposes port 8000 directly on the machine's interfaces (no `-p` mapping to forget).
- `--ipc=host` avoids shared-memory limits that break PyTorch data loading.

Verify the GPU is visible **before** installing anything else:
```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```
If this prints `False`, stop and fix it first; nothing downstream will use the GPU.

*Alternative (no Docker):* a venv plus a CUDA-enabled aarch64 PyTorch wheel from the GX10 documentation. Only do this if you've confirmed `torch.cuda.is_available()` is `True`.

### 8.2 System + Python dependencies
```bash
sudo apt update && sudo apt install -y espeak-ng ffmpeg libsndfile1 git
pip install fastapi "uvicorn[standard]" numpy opencv-python-headless \
            mediapipe kokoro soundfile pyyaml rapidfuzz
```
- `espeak-ng` is the grapheme-to-phoneme fallback Kokoro uses.
- Use `opencv-python-headless` on the server (no display attached).
- If `mediapipe` has no working aarch64 wheel, use the RetinaFace/face-alignment path from the Auto-AVSR repo and update §3.

### 8.3 Models
```bash
# VSR
git clone https://github.com/mpc001/auto_avsr third_party/auto_avsr
# Download the pretrained VSR checkpoint linked in its README → models/vsr_checkpoint.pth
pip install -r third_party/auto_avsr/requirements.txt   # skip pins that fight with the NGC torch

# TTS (cache weights locally while you still have internet)
python -c "from kokoro import KPipeline; KPipeline(lang_code='a')"
```
Record exact repo commit hashes and checkpoint filenames in `models/MANIFEST.md`.

### 8.4 Run
```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # only AFTER weights are cached
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### 8.5 Network (demo mode: direct cable)
```bash
ip link                                   # find wired interface, e.g. enP7s7
sudo nmcli con add type ethernet ifname enP7s7 con-name direct \
  ipv4.method manual ipv4.addresses 192.168.77.2/24
sudo nmcli con up direct
```
No gateway and no DNS on this connection (see §9 for why).

---

## 9. Setup: MacBook (client)

### 9.1 Dependencies
```bash
brew install portaudio
python3 -m venv .venv && source .venv/bin/activate
pip install opencv-python websockets sounddevice numpy pyyaml
```
`sounddevice` is a thin wrapper over PortAudio; the `brew` step must come first or the pip install won't be able to play audio.

### 9.2 macOS permissions
- **Camera:** System Settings → Privacy & Security → Camera → enable for the app you launch Python from (Terminal, iTerm, VS Code...). The first run triggers a prompt; if you dismissed it, the camera returns black frames or fails to open.
- **Audio output:** list devices with `python -m sounddevice` and set the device index in code/config if the default isn't the built-in speaker (e.g. Bluetooth headphones grabbing output).

### 9.3 Network (demo mode: direct cable)
Plug a USB-C-to-Ethernet adapter into the Mac, cable it to the Ascent, then:
```bash
networksetup -listallnetworkservices      # find the adapter's name
sudo networksetup -setmanual "USB 10/100/1000 LAN" 192.168.77.1 255.255.255.0
ping 192.168.77.2
```
- **Static IPs, no gateway.** With no router there's no DHCP, so addresses are assigned by hand. Omitting the gateway means the Mac keeps sending non-cable traffic over WiFi instead of down a dead-end cable.
- The `192.168.77.0/24` subnet was chosen to avoid colliding with the common `192.168.0.x` / `192.168.1.x` ranges of venue networks.

### 9.4 Run
```bash
python -m client.main
```

### 9.5 Dev mode (Tailscale)
For development away from the cable, set `network.server_host` to the Ascent's MagicDNS name or Tailscale IP (`tailscale ip -4` on the Ascent). Confirm `tailscale status` shows the peer as **direct**, not **relay**. A relayed connection adds noticeable latency. **Do not depend on Tailscale for the judged demo**: it needs its coordination server for logins and key refresh.

---

## 10. Latency Budget

Targets, **not measurements**. Fill in real numbers during testing using the `timings` field in the `done` message.

| Stage | Target |
|---|---|
| Key release → last frame received | < 50 ms |
| JPEG decode + ROI extraction (≈75 frames) | < 300 ms |
| VSR inference | < 800 ms |
| TTS time-to-first-audio | < 300 ms |
| Network return + playback start | < 50 ms |
| **Total** | **< 1.5–2 s** |

First-request latency will be much worse than steady state because of CUDA kernel initialization. That is why the server warms up at startup (§5.1).

---

## 11. Offline Hardening Checklist

- [ ] All model weights pre-downloaded and cached; `HF_HUB_OFFLINE=1` set on the Ascent.
- [ ] All `pip install` steps finished before leaving internet access.
- [ ] No telemetry, cloud API, or license-check calls in the pipeline (verify with `ss -tnp` / `lsof -i` while running).
- [ ] Static IPs configured; `ping` works with WiFi **off** on both machines.
- [ ] Full end-to-end run completed with WiFi off on **both** machines.
- [ ] Spare USB-C Ethernet adapter and spare cable packed.
- [ ] Backup path ready: travel router (private LAN) or phone hotspot.
- [ ] Server auto-starts, or a one-line start command is written on the demo cheat sheet.

---

## 12. Testing & Acceptance

### Acceptance criteria
1. With WiFi off on both machines, pressing SPACE, mouthing a phrase from `demo_phrases.txt`, and pressing SPACE again produces audible speech on the MacBook.
2. Correct phrase recognized on ≥ 8/10 attempts by each team member who will present.
3. Total key-release-to-audio latency under 2.5 s on 9/10 attempts.
4. Server survives: no face in frame, empty utterance, client disconnect mid-utterance, and 50 consecutive utterances.

### Test plan
- **Unit**: ROI extraction on a recorded clip; phrase matcher with known near-misses; PCM conversion round-trip.
- **Offline replay**: record 5–10 s clips per presenter and run the server pipeline on them directly (no network) to separate model accuracy from network problems.
- **Soak**: 50 utterances back-to-back; watch GPU memory and latency drift.
- **Venue rehearsal**: repeat in the actual lighting with the actual camera position.

### Stretch goals
- Automatic utterance endpointing from mouth-motion energy.
- Move ROI cropping to the client to cut bandwidth.
- Show the cropped mouth region in the preview for debugging.

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Lip-reading accuracy too low on new faces/lighting | Demo shows wrong words | Phrase-matching safety net; short phrases; fixed lighting and camera; show transcript |
| Wrong aarch64 wheels / CPU-only PyTorch | Slow or failing inference | NGC container; check `torch.cuda.is_available()` first |
| Ethernet adapter failure | No link | Spare adapter; travel-router and hotspot backups |
| Model tries to download at startup | Server hangs offline | Offline env vars; rehearsal with WiFi off |
| macOS camera permission denied | Black frames | Grant permission and test before the demo |
| First-request GPU lag | Awkward first demo attempt | Warm-up at startup; do a dry run before judges arrive |
| Preprocessing mismatch with Auto-AVSR | Silently poor accuracy | Reuse the repo's transforms; test on its sample clips first |

---

## 14. Proposed Repository Layout

```
.
├── SPEC.md
├── config.yaml
├── demo_phrases.txt
├── client/
│   ├── main.py            # webcam, preview, key toggle, websocket, playback
│   └── requirements.txt
├── server/
│   ├── main.py            # FastAPI app, websocket handler, warm-up
│   ├── roi.py             # MediaPipe mouth crop + smoothing
│   ├── vsr.py             # Auto-AVSR wrapper
│   ├── tts.py             # Kokoro wrapper
│   ├── phrases.py         # rapidfuzz matcher
│   └── requirements.txt
├── third_party/
│   └── auto_avsr/         # git clone (pin commit)
└── models/
    ├── MANIFEST.md
    └── vsr_checkpoint.pth
```

---

## 15. Open Questions

- Confirm the interpretation in §1 (lip reading → TTS, not audio → talking face).
- What phrases will the demo use? (Drives `demo_phrases.txt` and how much to rely on the matcher.)
- Which presenter(s) need to be tested against the VSR model?
- Does the Ascent run containers in the demo environment, or must it run natively?