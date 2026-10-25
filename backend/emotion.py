"""Track 4 (optional): emotion, so the voice can sound happy, sad...

Input:  video_path  the same clip the lip reader gets, uncropped (None if the user typed)
        text        the lip reader's raw text (unused for now)
Output: "neutral", "energetic", "sad" or "angry"

How: MediaPipe's face detector (the same model file the lip reader uses) finds the face in a few
frames, and HSEmotion (EfficientNet-B0 trained on AffectNet's real-world photos, 16 MB ONNX,
~10 ms a face on the CPU with cv2.dnn) scores 8 expressions. They are folded into our 4 (GROUPS),
averaged over the frames, and a feeling other than neutral needs its SURE level on average.
It replaced mini-XCEPTION (FER2013, 48 px grey faces), which read our angry frowns as fear or sad.
Setup: models/MANIFEST.md.  Try a clip on its own:  python emotion.py clip.webm
"""

import sys
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

MODELS = Path(__file__).parent.parent / "models"  # see models/MANIFEST.md
MODEL = MODELS / "enet_b0_8_best_vgaf.onnx"
FACE_MODEL = MODELS / "blaze_face_short_range.tflite"
CLASSES = ["anger", "contempt", "disgust", "fear", "happy", "neutral", "sad", "surprise"]  # model output order
GROUPS = {  # neutral first: it wins ties, and is the answer when no face was found
    "neutral": ["neutral", "surprise"],  # surprise: the open mouth of someone mouthing words, on our clips
    "energetic": ["happy", "contempt"],  # contempt: AffectNet's name for a lopsided smile, on our clips
    "sad": ["sad", "fear"],
    "angry": ["anger", "disgust"],
}
# Average probability each feeling needs over the frames looked at, else neutral (from our clips: real smiles
# score 0.5-0.9 and a mouthing face up to ~0.4; no neutral clip reached 0.2 angry, a frown reached 0.37)
SURE = {"energetic": 0.45, "sad": 0.3, "angry": 0.25}
LOOKS = 6  # frames looked at, spread over the clip
SIZE = 224  # the model's input, in pixels
MEAN, STD = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])  # ImageNet's, as it was trained

net = cv2.dnn.readNetFromONNX(str(MODEL))
# Not OpenCV's Haar cascade: OpenCV 5 (which mediapipe installs) no longer ships its files.
detector = vision.FaceDetector.create_from_options(
    vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)))
)
lock = threading.Lock()  # neither cv2.dnn nor the face detector is thread-safe


def sample_frames(video_path):
    """LOOKS frames spread over the clip, RGB.
    Chrome's .webm has no index (no seeking, no frame count), so the whole clip is decoded;
    only the ones looked at are converted, which is cheap. Looking at them is the slow part."""
    cap = cv2.VideoCapture(video_path)
    kept = []
    for i in range(10**6):
        if not cap.grab():
            break
        if i % 5 == 0:  # 5-6 candidates a second
            kept.append(cap.retrieve()[1])
    cap.release()
    picks = np.linspace(0, len(kept) - 1, min(LOOKS, len(kept))).astype(int) if kept else []
    return [cv2.cvtColor(kept[i], cv2.COLOR_BGR2RGB) for i in picks]


def find_face(rgb):
    """The biggest face, cropped square to its box (as AffectNet's faces are), or None."""
    with lock:
        found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).detections
    if not found:
        return None
    box = max(found, key=lambda f: f.bounding_box.width * f.bounding_box.height).bounding_box
    x, y = max(box.origin_x, 0), max(box.origin_y, 0)  # the box can stick out of the frame
    face = rgb[y:box.origin_y + box.height, x:box.origin_x + box.width]
    return face if face.size else None


def feel(face):
    """One face crop -> how likely each of GROUPS is."""
    x = (cv2.resize(face, (SIZE, SIZE), interpolation=cv2.INTER_AREA) / 255 - MEAN) / STD
    with lock:
        net.setInput(x.transpose(2, 0, 1)[None].astype(np.float32))
        logits = net.forward().ravel()
    p = np.exp(logits - logits.max())
    p = dict(zip(CLASSES, p / p.sum()))
    return {g: sum(p[c] for c in classes) for g, classes in GROUPS.items()}


def look_at(frames):
    """The faces' average of each group, over LOOKS of the frames ({} if no face was found)."""
    picks = np.linspace(0, len(frames) - 1, min(LOOKS, len(frames))).astype(int) if frames else []
    seen = [feel(face) for face in (find_face(frames[i]) for i in picks) if face is not None]
    return {g: float(np.mean([s[g] for s in seen])) for g in GROUPS} if seen else {}


def choose(average):
    """The strongest feeling that is SURE enough, else neutral."""
    feelings = [g for g in SURE if average.get(g, 0) >= SURE[g]]
    return max(feelings, key=average.get) if feelings else "neutral"


def detect_emotion(video_path: str | None, text: str) -> str:
    if not video_path:
        return "neutral"
    return choose(look_at(sample_frames(video_path)))


def detect_emotion_frames(frames: list) -> str:
    """The same from RGB frames already decoded (live lip reading, streaming.py)."""
    return choose(look_at(frames))


feel(np.zeros((SIZE, SIZE, 3), np.uint8))  # warm-up: the first run of each is slow
find_face(np.zeros((480, 640, 3), np.uint8))


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start = time.perf_counter()
        average = look_at(sample_frames(clip))
        scores = ", ".join(f"{g} {p:.2f}" for g, p in average.items())
        print(f"{clip}: {choose(average)} ({scores}) ({(time.perf_counter() - start) * 1000:.0f} ms)")
