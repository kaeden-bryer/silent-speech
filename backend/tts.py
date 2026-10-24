"""Track 3: text to speech.

Input:  text     what to say
        emotion  "neutral", "happy", "sad", "angry" or "surprised"
Output: MP3 audio as bytes, or None to let the browser read the text with its own voice.
"""


def text_to_speech(text: str, emotion: str) -> bytes | None:
    # TODO: call a realistic voice API (e.g. ElevenLabs) and return the MP3 bytes
    return None
