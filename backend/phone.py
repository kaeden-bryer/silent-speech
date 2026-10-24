"""Track 4 (optional): real phone calls (e.g. Twilio).

server.py calls start_call() when the user presses "Call", say() after every
sentence while the call is on, and hang_up() when they press "Hang up".

When the other person speaks, add it to `history` (the list given to start_call):
    history.append({"speaker": "them", "text": "..."})
The website shows it and correction.py uses it as context.

Routes Twilio needs (webhooks) go on `router`: server.py adds them to the app.
"""

from fastapi import APIRouter

router = APIRouter()


def start_call(number: str, history: list[dict]) -> None:
    # TODO: dial `number`
    raise NotImplementedError("phone calls are not set up yet")


def say(text: str, audio: bytes | None) -> None:
    # TODO: play `audio` (MP3) in the call, or read `text` aloud if audio is None
    pass


def hang_up() -> None:
    # TODO: end the call
    pass
