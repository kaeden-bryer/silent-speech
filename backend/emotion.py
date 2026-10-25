"""Track 4 (optional): emotion, so the voice can sound happy, sad...

Input:  video_path  the same clip the lip reader gets, uncropped (None if the user typed)
        text        the lip reader's raw text (unused for now)
Output: "neutral", "energetic", "sad" or "angry"

How: a rough guess from the face, a few frames per clip. OpenCV's built-in face detector
finds the face, and mini-XCEPTION (FER2013, 58k parameters, emotion.onnx, 236 KB) scores
64x64 grayscale crops on the CPU with cv2.dnn. No GPU, no extra packages, no download.
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
import numpy as np

MODEL = Path(__file__).with_name("emotion.onnx")  # from fer2013_mini_XCEPTION.102-0.66.hdf5
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
DETECT_WIDTH = 240  # frames are shrunk to this before looking for the face: faster

net = cv2.dnn.readNetFromONNX(str(MODEL))
faces = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
lock = threading.Lock()  # cv2.dnn is not thread-safe


def sample_frames(video_path):
    """Every EVERY-th frame, grayscale, DETECT_WIDTH wide.
    Chrome's .webm has no index (no seeking, no frame count), so the whole clip is decoded;
    only the candidates are converted, which is cheap. Looking at them is the slow part."""
    cap = cv2.VideoCapture(video_path)
    frames = []
    for i in range(10**6):
        if not cap.grab():
            break
        if i % EVERY:
            continue
        frame = cap.retrieve()[1]
        scale = DETECT_WIDTH / frame.shape[1]
        frames.append(cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY))
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


def find_face(gray):
    """The biggest face as a 64x64 crop, or None."""
    found = faces.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))
    if len(found) == 0:
        return None
    x, y, w, h = max(found, key=lambda f: f[2] * f[3])
    return cv2.resize(gray[y:y + h, x:x + w], (64, 64))


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
    """One guess per face looked at, in the order looked at."""
    frames = sample_frames(video_path)
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


find_face(np.zeros((180, DETECT_WIDTH), np.uint8))  # warm-up: the first run of each is slow
guess(np.zeros((64, 64), np.uint8))


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start = time.perf_counter()
        seen = votes(clip)
        feeling = max(GROUPS, key=seen.count)
        print(f"{clip}: {feeling}, votes {seen} ({(time.perf_counter() - start) * 1000:.0f} ms)")
