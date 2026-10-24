"""Emotion: how does the user feel? Sets the tone of the voice.  (Track 4, optional)

Select with EMOTION=<name> in backend/.env. To add an implementation, create a file with
an EmotionDetector subclass (see base.py) and register it here, e.g.
    "face": ".face:FaceEmotion",
"""

IMPLEMENTATIONS = {
    "neutral": ".neutral:NeutralEmotion",
}
FALLBACK = "neutral"
