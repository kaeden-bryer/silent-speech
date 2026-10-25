# Connecting the ML pipeline to the app (instructions for teammates)

Status: **nothing in the live app has been changed.** `backend/pipeline.py` and `backend/lm_fusion.py` are new files that
nothing imports yet. The changes below are a ready patch (`eval/integration/server_patch.diff`, 66 lines, touches only
`backend/server.py`) plus a frontend change you own. `python eval/integration/check_patched_server.py` applies the patch to a
temporary copy and drives the whole flow with a test client; it passes against the current `server.py`.

## The ML interface

```python
from pipeline import get_pipeline          # loads Auto-AVSR + Qwen once per process (about 20 s, then reused)
result = get_pipeline().recognize(video_path)
```
```python
{"raw_text": "...",            # Auto-AVSR's own best guess
 "final_text": "...",          # pipeline's pick; always one of Auto-AVSR's hypotheses or one of demo_phrases.txt; "" if unreadable
 "method": "visual_gate" | "lm_fusion" | "visual_fallback" | "failed",
 "alternatives": ["...", ...], # up to 4 other candidates the user may pick instead (raw_text first)
 "needs_confirmation": True,   # False only when the recogniser itself read exactly the gated phrase
 "latency_ms": 640.0,
 "details": {...}}             # scores (all named *_uncalibrated: log scores, NOT probabilities), timings, errors
```
`lip_read(video_path) -> str` is unchanged. The pipeline never speaks and never generates sentences. If Qwen is missing or fails it
returns the visual reading (`visual_fallback`); if the clip cannot be read it returns `final_text: ""` (`failed`).

## What the live app does today (read-only inspection)

`POST /api/video` -> `lipreading.lip_read` -> `speak()` -> `correction.correct` -> `emotion` -> `tts.text_to_speech` -> `history.append`
-> `phone.say` (if a call is on) -> JSON with the audio; the page then plays the audio at once (`new Audio(...).play()` or
`speechSynthesis`). Everything, including speaking into a phone call, happens before the user sees any text. Two further problems for the
confirmation flow: `correction.correct` snaps any text within fuzzy score 70 to a demo phrase, so it would rewrite words a user typed or
edited; and the raw (unconfirmed) text goes into the conversation `history`.

## Minimum changes

| file | change | why |
|---|---|---|
| `backend/server.py` | apply `eval/integration/server_patch.diff` | see below |
| `frontend/index.html` (Track 1) | preview + confirm UI, see snippet | the page currently auto-plays and reads `result.text`, which `/api/video` no longer returns |
| `backend/tts.py` | **none** | `text_to_speech(text, emotion)` already speaks whatever text it is given |
| `backend/correction.py` | **none** (stays for `/api/text`) | the phrase gate inside the pipeline replaces it for video; confirmed text bypasses it (`fix=False`) |
| `backend/requirements.txt` | add `transformers` and `safetensors` (versions in `eval/frozen_config.json`) | Qwen needs them; without them the pipeline still runs, visually only |

The server patch:
1. loads `pipeline` through the existing `load()` wrapper (a broken import just leaves the old `lipreading` path);
2. `POST /api/video` now returns the recognition (`clip_id`, `raw_text`, `final_text`, `method`, `alternatives`, `needs_confirmation`,
   `latency_ms`) and **nothing else**: no audio, no history entry, no phone speech, no emotion/TTS;
3. new `POST /api/speak {"text": "...", "clip_id": "..."}`, called only after the user confirms or edits: runs the existing `speak()` with
   `fix=False` (no fuzzy rewrite), so TTS, emotion, history and `phone.say` happen only here;
4. if the pipeline is missing or raises, `/api/video` falls back to plain `lip_read` and still asks for confirmation.

Not changed (decide separately): `POST /api/text` still speaks typed text immediately and still passes it through `correction.correct`, which can
silently replace typed words with a demo phrase. Typed text is the user's own, so I would call `speak(text, fix=False)` there too.

## Frontend contract (sketch)

```js
const r = await (await fetch("/api/video", {method: "POST", body: form})).json();
if (!r.final_text) return show("Couldn't read that: try again");
showPreview(r.final_text, r.alternatives);            // editable text box + one button per alternative + [Speak] [Discard]
// r.needs_confirmation === true  -> require an explicit tap on [Speak] after the user looked at / edited the text
// r.needs_confirmation === false -> may highlight [Speak] as a one-tap default; still never speak without a tap
async function onSpeak(text) {                         // text = box content (original, an alternative, or typed by the user)
  const s = await (await fetch("/api/speak", {method: "POST", headers: {"Content-Type": "application/json"},
                   body: JSON.stringify({text, clip_id: r.clip_id})})).json();
  if (s.audio) new Audio("data:audio/mpeg;base64," + s.audio).play(); else speechSynthesis.speak(new SpeechSynthesisUtterance(s.text));
}
```
Do not show `details` scores to users as percentages or "confidence": they are uncalibrated log scores. `method` is useful for a small hint
("matched a saved phrase" / "best guess").

## Operational notes

- Start-up: Auto-AVSR + Qwen + Kokoro need about 6-7 GB of GPU together (measured: 4.0 GB for the first two, see `PIPELINE_DEV_REPORT.md`). The first
  `get_pipeline()` takes about 20 s; do it at server start (the existing modules also load at import).
- Everything is offline: Qwen is loaded with `local_files_only` and a pinned revision; no API calls anywhere.
- `backend/demo_phrases.txt` is part of the frozen configuration: the gate threshold was set for these 8 phrases. If you edit the file,
  `details.phrases_match_frozen` becomes false and `eval/final_test.py verify` fails. More phrases make the gate stricter, fewer make it looser.
- History is not used by the pipeline (it was not evaluated: the dev set has no dialogue). `history.append` should only receive confirmed text.
- Concurrency: the pipeline serialises GPU work internally (locks around Auto-AVSR and Qwen); FastAPI's threadpool is fine.
- Order of work suggested: (1) apply the server patch and update the page together, since the old page cannot read the new `/api/video` response;
  (2) run `check_patched_server.py` again after merging; (3) commit, then run the final held-out evaluation once (`eval/final_test.py`).
