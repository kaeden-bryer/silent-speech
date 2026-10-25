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
| Call settings that do something | Should | Persisted toggles: live captions, opening line, hold-on filler | Opening line / filler = canned audio into calls; captions = transcription of the other side |

## Parked in the frontend (built, hidden from nav)

**The phone-call channel** — `frontend/src/screens/Conversation.jsx`, a complete mockup kept as an idea: sessions sidebar, live captions of the other person as chat turns, emotion + "✓ confirmed" chips, quick-phrase row, speaker-mode toggle, hang-up. Re-add it to `SCREENS` in `App.jsx` to bring it back. Needs: Twilio Media Streams in `backend/phone.py` (dial out, play TTS into the call, transcribe the other side into history), plus history polling. The API routes (`/api/call`, `/api/hangup`, `/api/history`) already exist as placeholders.

Related call features from the brief, not started:
- Live captions of the other caller (ElevenLabs Scribe / Deepgram) — Should
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
- **Session management UI** (multiple conversations) — lives in the parked call screen; the backend keeps one global history for now.
- **Fake confidence percentages** — removed from the wired UI; bring back real ones when the model provides them.
