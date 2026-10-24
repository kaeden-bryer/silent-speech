"""Track 4 (optional): emotion, so the voice can sound happy, sad...

Input:  video_path  the same clip the lip reader gets (None if the user typed)
        text        the lip reader's raw text
Output: "neutral", "happy", "sad", "angry" or "surprised"
"""


def detect_emotion(video_path: str | None, text: str) -> str:
    # TODO: look at the face in the video
    return "neutral"
