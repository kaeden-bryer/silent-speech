"""Write synthetic clips and a manifest to check that the evaluation harness runs end to end.

    python eval/make_smoke_clips.py OUT_DIR

The face is the public-domain astronaut photo that ships with scikit-image, held still, so
the clips contain no speech and no private data. There are no ground-truth transcripts: the
numbers from this manifest say whether the machinery works, nothing about accuracy.
"""

import csv
import sys
from pathlib import Path

import cv2
import numpy as np
from skimage import data


def write(path, frames, fps=25):
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for f in frames:
        out.write(f)
    out.release()


def main(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    face = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    black = np.zeros_like(face)
    write(out_dir / "still_face_2s.avi", [face] * 50)
    write(out_dir / "still_face_3s.avi", [face] * 75)
    write(out_dir / "no_face_2s.avi", [black] * 50)
    write(out_dir / "too_short.avi", [face] * 5)
    rows = [
        ("still_face_2s.avi", "", "silent+no_speech"),
        ("still_face_3s.avi", "", "silent+no_speech"),
        ("no_face_2s.avi", "", "no_speech"),
        ("still_face_2s.avi", "", "silent+unseen"),  # unlabelled on purpose: exercises the "not scored" path
        ("too_short.avi", "", "silent+unseen"),
    ]
    with open(out_dir / "manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_path", "text", "category"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out_dir / 'manifest.csv'}")


if __name__ == "__main__":
    main(sys.argv[1])
