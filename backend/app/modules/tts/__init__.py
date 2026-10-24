"""Text-to-speech: corrected text + emotion -> audio.  (Track 3)

Select with TTS=<name> in backend/.env. To add an implementation, create a file with a
TTSEngine subclass (see base.py) and register it here, e.g.
    "elevenlabs": ".elevenlabs:ElevenLabsTTS",
"""

IMPLEMENTATIONS = {
    "browser": ".browser:BrowserTTS",
}
FALLBACK = "browser"
