# Feature ideas & wishlist

Everything we want that is **not fully built yet** — either mocked in the frontend, parked out of the nav, or not started. Sources: the team research brief ("Your voice, anywhere"), the parked call screen, and the current mockups. The baseline that IS wired today: camera clip → lip read → correction → spoken reply (browser voice), with a typed fallback and a raw-vs-corrected pick.

Priorities follow the brief: **Must** = demo fails without it · **Should** = makes it convincing · **Nice** = pitch or build if time allows.

## Built in the frontend, waiting on the backend

| Feature | Priority | Frontend state | Backend needs |
|---|---|---|---|
| Voice cloning from a short recording | Must | Setup screen mockup (record 30s / upload) | Clone endpoint + TTS with the cloned voice (Cartesia Sonic — sponsor track) |
| Top-3 "did you say…" candidates | Must | UI shows corrected + raw today; built for 3 | n-best list from the lip reader (Auto-AVSR beam search already produces one) + per-candidate confidence in the response |
| Confirm before speaking numbers/dates | Should | Hint text only | Flag risky tokens (dates, doses, addresses) in the response so the UI can gate auto-speak |
| Emotion → tone of voice | Nice | Emotion chip renders when ≠ neutral | Real `detect_emotion` (facial expression / text sentiment) + TTS that uses it |
| Stock voice fallback | Should | Mentioned in Setup copy | A default TTS voice when no clone exists (Kokoro already does this once wired) |
| Phrase bank (one tap, never misread) | Should | Static chips in Setup + Settings | Store per-user phrases; speak them without the lip-reading path |
| Live partial transcript while mouthing | Nice | "Reading…" overlay exists | Streaming recognition (current API is per-clip); CLAUDE.md's WebSocket design is the natural fit |
| Call settings that do something | Should | Live captions and hear-myself work; the opening line and hold-on filler toggles were removed from Settings until they do something | Opening line / filler = canned audio sent into the call by `phone.py` when it's answered / while the user mouths |

**Parked: the Setup screen** (`frontend/src/screens/Setup.jsx`, out of the nav): voice-cloning mockup, permission checklist, phrase bank. Nothing in it is wired yet (the camera is asked for when first used anyway). Re-add it to `SCREENS` in `App.jsx` once voice cloning or the phrase bank works.

## Phone calls (built, needs the internet)

**The phone-call channel** is wired: the Call screen (`frontend/src/screens/Conversation.jsx`) dials a real number through Twilio Media Streams (`backend/phone.py`). Mouthed (hold to speak, live), typed or quick-phrase sentences are spoken into the call with Kokoro. The other side is heard live on the phone (`/api/call/audio`, only with the dialing screen's key) and transcribed locally (`backend/stt.py`, Whisper large-v3-turbo) into history as captions. It needs internet on the Ascent plus the `app.silent-speech.us` tunnel; everything else stays offline. The old mockup's sessions sidebar, emotion / "✓ confirmed" chips and speaker-mode toggle were dropped. Bring them back if there's time.

Related call features from the brief, not started:
- Fully offline calls (no Twilio): a LAN call to a second phone on the SilentSpeech Wi-Fi. Keep `start_call/say/hang_up` as the seam — Nice
- Suggested replies from what was just said (Claude, tidy-only guardrails) — Should
- Opening line + hold-on filler during pauses (callers hang up on silence) — Should
- Phone menu helper ("press 1 for…") — Nice
- Incoming calls + call history with transcript — Nice

## Not started anywhere (from the research brief)

| Feature | Priority | Notes |
|---|---|---|
| Lip calibration (mouth 10–20 prompted phrases) | Should | Accuracy varies a lot between people; SRAVI's lesson |
| Clone voice from old voicemails/videos | Nice | Most people never banked their voice |
| Meetings: virtual mic into Zoom/Meet/Teams | Should | BlackHole, Mac + Chrome/Edge only; pitch as future work on phones |
| "I want to speak" cue in meetings | Nice | Silent users miss the gap to jump in |
| Bedside quick board (pain, yes/no, nurse, family) | Should | ICU users are weak; full sentences are too much effort |
| Big-text display facing the listener / caregiver view | Nice | Loud rooms, masked staff |
| Emergency one-tap message (name, address, "I breathe through a stoma") | Nice | Mouthing under panic is unreliable |
| Call an emergency contact on loop until answered | Nice | Safe to demo |
| Highlight words the app changed + smoothing off/light/full | Nice | Users need to see when the app guessed |
| Tone from facial expression | Nice | Flat delivery strips emotion |
| Text-to-911 fallback | Cut | Out of scope for the demo |

## Dropped / consciously deferred

- **Health/pipeline status panel** — the old backend had `/api/health`; the new flat backend doesn't. Re-add only if module fallbacks confuse demo watchers.
- **Session management UI** (multiple conversations) — the old call mockup had a sidebar for it; the backend keeps one global history for now (the Call screen shows only the current call).
- **Fake confidence percentages** — removed from the wired UI; bring back real ones when the model provides them.
