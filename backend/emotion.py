"""Track 4 (optional): emotion, so the voice can sound happy, sad...

Input:  video_path  the same clip the lip reader gets, uncropped (None if the user typed)
        text        the lip reader's raw text (unused for now)
Output: "neutral", "energetic", "sad" or "angry"

How: a rough guess from the face, a few frames per clip. MediaPipe's face detector (the same
model file the lip reader uses) finds the face, and mini-XCEPTION (FER2013, 58k parameters,
emotion.onnx, 236 KB) scores 64x64 grayscale crops on the CPU with cv2.dnn. No GPU.
Its 7 emotions are folded into our 4, see GROUPS.
Frames are looked at middle first (1/2, then 1/4 and 3/4, then the 1/8ths...), each one
votes, and it stops as soon as one emotion has CONFIRM votes.
Try a clip on its own:  python emotion.py clip.webm
"""

import sys
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

MODEL = Path(__file__).with_name("emotion.onnx")  # from fer2013_mini_XCEPTION.102-0.66.hdf5
FACE_MODEL = Path(__file__).parent.parent / "models" / "blaze_face_short_range.tflite"  # see models/MANIFEST.md
FER2013 = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]  # model output order
GROUPS = {  # neutral first: it wins ties, and is the answer when no face was found
    "neutral": ["neutral"],
    "energetic": ["happy", "surprise"],
    "sad": ["sad", "fear"],
    "angry": ["angry", "disgust"],
}
CONFIRM = 3  # stop once this many frames agree
MAX_LOOKS = 9  # never look at more frames than this, even if they keep disagreeing
EVERY = 6  # only every 6th frame is a candidate (5 per second at 30 fps)

net = cv2.dnn.readNetFromONNX(str(MODEL))
# Not OpenCV's Haar cascade: OpenCV 5 (which mediapipe installs) no longer ships its files.
detector = vision.FaceDetector.create_from_options(
    vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)))
)
lock = threading.Lock()  # neither cv2.dnn nor the face detector is thread-safe


def sample_frames(video_path):
    """Every EVERY-th frame, RGB.
    Chrome's .webm has no index (no seeking, no frame count), so the whole clip is decoded;
    only the candidates are converted, which is cheap. Looking at them is the slow part."""
    cap = cv2.VideoCapture(video_path)
    frames = []
    for i in range(10**6):
        if not cap.grab():
            break
        if i % EVERY:
            continue
        frames.append(cv2.cvtColor(cap.retrieve()[1], cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def middle_first(n):
    """0..n-1 in the order: middle, then the middles of both halves, then of the quarters..."""
    order, parts = [], [(0, n)]
    while parts:
        halves = []
        for lo, hi in parts:
            if lo < hi:
                mid = (lo + hi) // 2
                order.append(mid)
                halves += [(lo, mid), (mid + 1, hi)]
        parts = halves
    return order


def find_face(rgb):
    """The biggest face as a 64x64 grayscale crop, or None."""
    with lock:
        found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).detections
    if not found:
        return None
    box = max(found, key=lambda f: f.bounding_box.width * f.bounding_box.height).bounding_box
    # Framed like the Haar detector this was tuned with (measured on our clips):
    # 15% bigger, and a sixth of its width higher, so it shows more forehead
    size = 1.15 * box.width
    cx, cy = box.origin_x + box.width / 2, box.origin_y + box.height / 2 - box.width / 6
    x, y = int(max(cx - size / 2, 0)), int(max(cy - size / 2, 0))  # the box can stick out of the frame
    face = rgb[y:int(cy + size / 2), x:int(cx + size / 2)]
    if face.size == 0:
        return None
    return cv2.resize(cv2.cvtColor(face, cv2.COLOR_RGB2GRAY), (64, 64), interpolation=cv2.INTER_AREA)


def guess(face):
    """One 64x64 uint8 face -> one of GROUPS."""
    blob = (face.astype(np.float32) / 255 - 0.5) * 2  # the [-1, 1] range it was trained on
    with lock:
        net.setInput(blob[None, None])  # 1 x 1 x 64 x 64
        logits = net.forward().ravel()
    p = np.exp(logits - logits.max())  # softmax here: cv2.dnn gets the model's own one wrong
    p = dict(zip(FER2013, p / p.sum()))
    return max(GROUPS, key=lambda g: sum(p[e] for e in GROUPS[g]))


def votes(video_path):
    return look_at(sample_frames(video_path))


def look_at(frames):
    """One guess per face looked at, in the order looked at."""
    seen = []
    for i in middle_first(len(frames))[:MAX_LOOKS]:
        face = find_face(frames[i])
        if face is None:
            continue
        seen.append(guess(face))
        if seen.count(seen[-1]) == CONFIRM:
            break
    return seen


def detect_emotion(video_path: str | None, text: str) -> str:
    if not video_path:
        return "neutral"
    seen = votes(video_path)
    return max(GROUPS, key=seen.count)  # the most votes; no votes or a tie: neutral


def detect_emotion_frames(frames: list) -> str:
    """The same from RGB frames already decoded (live lip reading, streaming.py)."""
    return max(GROUPS, key=look_at(frames[::EVERY]).count)


find_face(np.zeros((480, 640, 3), np.uint8))  # warm-up: the first run of each is slow
guess(np.zeros((64, 64), np.uint8))


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start = time.perf_counter()
        seen = votes(clip)
        feeling = max(GROUPS, key=seen.count)
        print(f"{clip}: {feeling}, votes {seen} ({(time.perf_counter() - start) * 1000:.0f} ms)")
