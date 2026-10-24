# Lip reading (track 2)

**Job:** turn a short silent clip of someone mouthing one sentence into text. Mistakes are fine: the correction module fixes them using context.

**Contract:** `LipReader.transcribe(video_path) -> Transcript` in [base.py](base.py).
The clip comes straight from the browser's MediaRecorder:
- `.webm` (Chrome, Android, Firefox) or `.mp4` (Safari, iOS)
- front camera, about 640×480
- variable frame rate, no audio
- usually 1–5 s long

**Placeholder:** [mock.py](mock.py) returns noisy sample sentences.

## Test alone

```bash
python -m app.modules.lipreading path/to/clip.webm --impl <yours>
```

For realistic test clips, set `SAVE_RECORDINGS=1` in `.env` and record from the web page. The clips are saved in `backend/data/recordings/`.

## Notes

- Suggested model: [Auto-AVSR](https://github.com/mpc001/auto_avsr), using a VSR (video-only) checkpoint. Clone repos into `backend/third_party/` and put weights in `backend/models/` (both gitignored).
- These models are usually trained on 25 fps video, while browser clips have a variable frame rate. ffmpeg can resample them.
- Decide early where the model runs for the demo (a laptop with a GPU? a cloud GPU?). If it runs remotely, your implementation can simply send the clip to the GPU server over HTTP.
- n-best alternatives could help the corrector. To add them, agree on an optional field in `Transcript` with track 3 first.
