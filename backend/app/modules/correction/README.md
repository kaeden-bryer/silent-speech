# Correction (track 3)

**Job:** lip reader output is noisy ("can i half a coffee wiz oat milk"). Return what the person meant ("Can I have a coffee with oat milk?"), using the conversation so far.

**Contract:** `TextCorrector.correct(raw_text, context) -> str` in [base.py](base.py).
`context.turns` holds the recent turns, oldest first. `speaker` is `"user"` (our user) or `"other"` (the person they're talking to, filled in during phone calls).

**Placeholder:** [passthrough.py](passthrough.py) returns the text unchanged.

## Test alone

```bash
python -m app.modules.correction "can i half a coffee wiz oat milk" --impl <yours>
python -m app.modules.correction "yes too sugars" --context "Would you like sugar?" --impl <yours>
```

## Notes

- Latency is the main constraint: this is a live conversation. Each response's `stages` gives the time per stage.
- Lip reading confuses sounds that look alike on the lips (p/b/m, f/v, t/d/n, k/g), drops short words, and merges or splits words.
- It's the user's voice, not a chatbot: it must never answer or add to what they said.
- Read API keys with `os.getenv` in `load()`, and add the variable names (empty) to `.env.example`.
