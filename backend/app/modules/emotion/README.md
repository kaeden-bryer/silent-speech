# Emotion (track 4, optional)

**Job:** guess how the user feels while speaking, so the voice can sound happy, sad, angry…

**Contract:** `EmotionDetector.detect(video_path, text) -> Emotion` in [base.py](base.py).
- `video_path` is the same clip the lip reader gets, or `None` for typed input.
- `text` is the raw transcript.
- Return a label from `EmotionLabel` ([schemas.py](../../schemas.py)) and an intensity from 0 to 1.
- It runs in parallel with the correction call, so it adds no delay as long as it's faster than correction.

**Placeholder:** [neutral.py](neutral.py) always returns neutral.

## Test alone

```bash
python -m app.modules.emotion --video data/recordings/some_clip.webm --impl <yours>
python -m app.modules.emotion --text "i am so happy" --impl <yours>
```

## Notes

- A facial-expression model on a few frames of the clip is the obvious start.
- Mouthing words distorts the mouth, so the eyes and eyebrows are more reliable signals.
- Text sentiment is a cheap complement, and the only signal for typed input.
- New labels go in `EmotionLabel` in schemas.py. Tell track 3 (TTS) and track 1 (browser voice) when you add one.
