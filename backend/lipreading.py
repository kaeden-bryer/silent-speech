"""Track 2: lip reading.

Input:  path to a short video of someone mouthing one sentence
        (.webm from Chrome/Android, .mp4 from iPhone, no sound)
Output: the text they said. Mistakes are fine, correction.py fixes them.

How: Auto-AVSR (third_party/auto_avsr), using its own mouth cropping and transforms.
MediaPipe finds the eyes, nose and mouth in every frame, the face is aligned to a
mean face, and a 96x96 mouth patch is cut out. The model is loaded once, at import.
Setup: models/MANIFEST.md.  Try a clip on its own:  python lipreading.py clip.webm
"""

import os
import sys
import threading
import time
from pathlib import Path

# torch 2.14 compiles some ops with Triton on first use, which needs python3-dev headers.
# Plain CUDA kernels are fine here. Must be set before torch is imported.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

import cv2
import mediapipe as mp
import numpy as np
import torch
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "third_party" / "auto_avsr"))
from datamodule.transforms import TextTransform, VideoTransform  # noqa: E402
from espnet.nets.batch_beam_search import BatchBeamSearch  # noqa: E402
from espnet.nets.pytorch_backend.e2e_asr_conformer import E2E  # noqa: E402
from preparation.detectors.mediapipe.video_process import VideoProcess  # noqa: E402

CHECKPOINT = ROOT / "models" / "vsr_trlrs2lrs3vox2avsp_base.pth"
FACE_MODEL = ROOT / "models" / "blaze_face_short_range.tflite"
DEVICE = "cuda"
FPS = 25  # the model was trained on 25 fps video
BEAM_SIZE = 10  # the repo uses 40: slightly better, slower
MIN_FRAMES = 10  # shorter than ~0.4 s: nothing was said
MAX_MISSING = 0.3  # give up if the face is missing in more frames than this

detector = vision.FaceDetector.create_from_options(
    vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)))
)
video_process = VideoProcess(convert_gray=False)
video_transform = VideoTransform(subset="test")
text_transform = TextTransform()

model = E2E(len(text_transform.token_list), "video")
model.load_state_dict(torch.load(CHECKPOINT, map_location="cpu"))
model.to(DEVICE).eval()
beam_search = BatchBeamSearch(
    beam_size=BEAM_SIZE,
    vocab_size=len(text_transform.token_list),
    weights={"decoder": 0.9, "ctc": 0.1},
    scorers=model.scorers(),
    sos=model.odim - 1,
    eos=model.odim - 1,
    token_list=text_transform.token_list,
    pre_beam_score_key="decoder",
).to(DEVICE).eval()
gpu = threading.Lock()  # one clip at a time


def read_frames(video_path):
    """RGB frames, resampled to 25 fps (phones record at 30 fps or a variable rate)."""
    cap = cv2.VideoCapture(video_path)
    native_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    frames, times = [], []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        times.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
    cap.release()
    if not frames:
        raise ValueError(f"could not read any frames from {video_path}")
    times = np.array(times)
    if not np.all(np.diff(times) > 0):  # no usable timestamps: trust the header
        times = np.arange(len(frames)) / native_fps
    wanted = np.arange(times[0], times[-1] + 1e-6, 1 / FPS)
    picks = np.clip(np.searchsorted(times, wanted), 0, len(frames) - 1)
    return [frames[i] for i in picks]


def find_face(frame):
    """Right eye, left eye, nose tip, mouth centre in pixels (the 4 points the repo uses), or None."""
    faces = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)).detections
    if not faces:
        return None
    face = max(faces, key=lambda f: f.bounding_box.width * f.bounding_box.height)
    h, w = frame.shape[:2]
    return np.array([[k.x * w, k.y * h] for k in face.keypoints[:4]])


def decode(video):
    """video: T x 1 x 88 x 88 tensor, already transformed. Returns lowercase text."""
    with gpu, torch.no_grad():
        x = model.proj_encoder(model.frontend(video.unsqueeze(0).to(DEVICE)))
        enc, _ = model.encoder(x, None)
        best = beam_search(enc.squeeze(0))[0]
    ids = torch.tensor([int(i) for i in best.yseq[1:]])
    return text_transform.post_process(ids).replace("<eos>", "").strip().lower()


def lip_read(video_path: str) -> str:
    frames = read_frames(video_path)
    if len(frames) < MIN_FRAMES:
        return ""
    landmarks = [find_face(f) for f in frames]
    missing = sum(lm is None for lm in landmarks) / len(landmarks)
    if missing > MAX_MISSING:
        raise ValueError(f"face not found in {missing:.0%} of frames")
    mouth = video_process(np.stack(frames), landmarks)  # T x 96 x 96 x 3
    video = video_transform(torch.tensor(mouth).permute(0, 3, 1, 2))
    return decode(video)


decode(torch.randn(50, 1, 88, 88))  # warm-up: the first GPU run is slow


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start = time.perf_counter()
        text = lip_read(clip)
        print(f"{clip}: {text!r} ({time.perf_counter() - start:.2f}s)")
