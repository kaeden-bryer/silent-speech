# Phone calls (track 4, optional)

**Job:** let the user call someone on a real phone and talk through the app. For the demo: call a judge.

**Contract:** `Telephony` in [base.py](base.py): `start_call`, `hang_up`, `say`, plus an optional `router` for your provider's webhooks.

The core already does this:
- serves `POST /api/call/start` and `/api/call/hangup`
- keeps `session.call_id` up to date
- calls `say()` after each utterance while a call is active

You also need to:
- add the other person's words with `session.add_turn("other", text)`. The frontend shows them and the corrector uses them as context.
- set `session.call_id = None` when the call ends on its own.

**Placeholder:** [disabled.py](disabled.py). The call endpoints answer 503.

## Test

There's no command-line runner, because a call needs a live phone line. `test_utterances_are_said_into_an_active_call` in [tests/test_app.py](../../../tests/test_app.py) shows the flow with a fake phone.

## Notes

- Twilio is the usual choice. Your provider has to reach the backend: run a tunnel (see the root README) and use its public URL for webhooks.
- `result.audio_url` is a path on the backend: prefix it with the public URL so the provider can fetch it. When it's `None`, use the provider's own text-to-speech on `result.text`.
- The simplest flow is turn-based:
  1. Play the user's sentence into the call.
  2. Transcribe the other side with the provider's speech recognition.
  3. Store it as `"other"` turns. The frontend polls `GET /api/session/{id}` to show them.
- Harder, but better: stream the call audio to the browser so the user hears the other person live.
- Trial accounts can usually only call verified numbers.
