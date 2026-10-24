# Text-to-speech (track 3)

**Job:** speak the corrected sentence in a realistic voice, with a tone that matches the emotion.

**Contract:** `TTSEngine.synthesize(text, emotion) -> SpeechAudio | None` in [base.py](base.py).
- **Return audio** (bytes + `mime_type`): it's served at `/api/audio/<id>`, played by the browser, and played into the phone line during calls.
- **Return `None`:** the browser speaks `text` with its built-in voice.

**Placeholder:** [browser.py](browser.py) returns `None`.

## Test alone

```bash
python -m app.modules.tts "Hi, nice to meet you!" --emotion happy --impl <yours>
```

The audio is written to `backend/data/tts/`.

## Notes

- Emotion labels are in `EmotionLabel` ([schemas.py](../../schemas.py)), with an intensity from 0 to 1. Until track 4 delivers, it's always neutral.
- Latency matters as much as quality: the listener is waiting.
- Read API keys with `os.getenv` in `load()`, and add the variable names (empty) to `.env.example`.
