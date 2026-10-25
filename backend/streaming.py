"""Track 2 (live): lip reading while the user is still mouthing, so the voice starts right away.

The phone sends camera frames (JPEG) while the button is held. Every STEP seconds the window is
read again with lipreading.py's model, and words are said as soon as they are sure:
- the last AGREE readings agree on them: a word that is still being mouthed keeps changing,
- the reading is CONFIDENT: from a still or half-seen mouth the model makes up fluent
  sentences ("we're going to talk about..."), but with a low score,
- they are not the reading's last word, which may still be in progress, unless the readings
  stopped changing (a pause) or the button was released.
After a pause the window starts again after it, so the readings stay short and fast.

    hold = start()
    add_frame(hold, data)  # data: the time in ms (8 bytes, float64, little-endian) + one JPEG frame
    step(hold)             # -> {"say": [words to say now], "heard": all words said, "pending": ..., "face": bool}
    finish(hold)           # the button was released -> the words still to say
Replay recorded clips as if they were live:  python streaming.py clip.webm
"""

import os
import struct
import sys
import time
from bisect import bisect_left
from difflib import SequenceMatcher

os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")  # see lipreading.py

import cv2
import numpy as np
import torch

import lipreading as lp

# Tuned by replaying the 45 recorded clips (see replay()): with these, what is said live differs
# from reading each whole clip at the end about as much as the JPEG compression alone does.
STEP = 0.3  # seconds of new video between two readings (a reading takes ~0.17 s)
FIRST = 0.6  # seconds of video before the first reading
AGREE = 4  # readings in a row that must agree on a word before it is said
CONFIDENT = -1.2  # score per token: real readings are above about -1, made-up ones below about -1.5
PAUSE = 3  # readings in a row that did not change at all: the user paused
KEEP = 0.3  # seconds kept before the cut when the window starts again after a pause
MAX_WINDOW = 10  # seconds: a longer window is cut even without a pause (slow to read)
JPEG_QUALITY = 85  # replay only, like the phone: at 70 the lip reader already reads clearly worse


def start():
    """A new hold of the button."""
    return {
        "times": [],  # seconds, one per frame received
        "frames": [],  # one future per frame -> (RGB frame or None, face points or None)
        "start": 0,  # index of the window's first frame
        "said": [],  # words said since the window started
        "spoken": [],  # every word said during this hold
        "readings": [],  # the last readings' words (None when not confident)
        "last_sure": None,  # the words of the last confident reading in this window
        "read_at": 0,  # how many frames there were at the last reading
        "stopped": False,  # the button was released (set by server.py)
    }


def look(jpeg):
    """One frame from the phone -> (RGB frame, face points), found on lipreading.py's face threads."""
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None, None
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return rgb, lp.find_face(rgb)


def add_frame(hold, data):
    (ms,) = struct.unpack("<d", data[:8])
    if hold["times"] and ms / 1000 <= hold["times"][-1]:  # late or repeated frame
        return
    hold["times"].append(ms / 1000)
    hold["frames"].append(lp.face_pool.submit(look, data[8:]))


def due(hold):
    """Enough new video for another reading?"""
    return len(hold["frames"]) - hold["read_at"] >= STEP * lp.FPS


def window(hold, first=None):
    """The frames since the window start (or `first`), at 25 fps like the model was trained on: (frames, face points)."""
    first = hold["start"] if first is None else first
    looked = [(t, *f.result()) for t, f in zip(hold["times"][first:], hold["frames"][first:])]
    looked = [x for x in looked if x[1] is not None]
    if not looked:
        return [], []
    times = np.array([t for t, _, _ in looked])
    picks = np.clip(np.searchsorted(times, np.arange(times[0], times[-1] + 1e-6, 1 / lp.FPS)), 0, len(looked) - 1)
    return [looked[i][1] for i in picks], [looked[i][2] for i in picks]


def read(frames, landmarks):
    """(words, score per token), or None when the face is not seen well enough."""
    if sum(lm is None for lm in landmarks) > lp.MAX_MISSING * len(landmarks):
        return None
    try:
        mouth = lp.video_process(np.stack(frames), list(landmarks))  # T x 96 x 96 x 3
    except (ValueError, OverflowError, AssertionError, cv2.error):  # e.g. face at the edge, phone turned
        return None
    video = lp.video_transform(torch.tensor(mouth).permute(0, 3, 1, 2))
    with lp.gpu, torch.no_grad():
        x = lp.model.proj_encoder(lp.model.frontend(video.unsqueeze(0).to(lp.DEVICE)))
        enc, _ = lp.model.encoder(x, None)
        best = lp.beam_search(enc.squeeze(0))[0]  # the same search as whole clips: the same words
    ids = torch.tensor([int(i) for i in best.yseq[1:]])
    text = lp.text_transform.post_process(ids).replace("<eos>", "").strip().lower()
    return text.split(), float(best.score) / max(len(ids), 1)


def after(said, words):
    """The words of a reading that come after what was already said: the model may change its
    mind about a word it already read ("use signal" -> "use the signal"), so they are lined up."""
    end = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, said, words, autojunk=False).get_opcodes():
        if i1 >= len(said):  # past everything said: new words
            break
        end = j1 + min(i2 - i1, j2 - j1) if op == "replace" else j2
    return words[end:]


def common_start(readings):
    words = []
    for column in zip(*readings):
        if any(w != column[0] for w in column):
            break
        words.append(column[0])
    return words


def step(hold):
    """Read the window again. Returns the words that are now sure, to say right away."""
    frames, landmarks = window(hold)
    hold["read_at"] = len(hold["frames"])
    if len(frames) < FIRST * lp.FPS:
        return {"say": [], "heard": " ".join(hold["spoken"]), "pending": "", "face": True}
    reading = read(frames, landmarks)
    if reading is None:
        hold["readings"] = []
        return {"say": [], "heard": " ".join(hold["spoken"]), "pending": "", "face": False}
    words, score = reading
    sure = score >= CONFIDENT
    hold["readings"] = (hold["readings"] + [words if sure else None])[-max(AGREE, PAUSE):]
    if sure:
        hold["last_sure"] = words
    recent = hold["readings"][-AGREE:]
    paused = len(hold["readings"]) >= PAUSE and all(r == words for r in hold["readings"][-PAUSE:])
    say = []
    if sure and len(recent) == AGREE and None not in recent:
        rest = after(hold["said"], words)
        say = rest if paused else common_start([after(hold["said"], r) for r in recent])
        if say == rest and not paused:
            say = say[:-1]  # the reading's last word may still be in progress
    hold["said"] += say
    hold["spoken"] += say
    rest = after(hold["said"], words) if sure else []
    seconds = len(frames) / lp.FPS
    if (paused and not rest) or seconds > MAX_WINDOW:
        if seconds > MAX_WINDOW and sure:  # cut without a pause: say what was read so far
            say += rest
            hold["spoken"] += rest
        cut = hold["times"][-1] - (KEEP if paused else 0)
        hold.update(start=bisect_left(hold["times"], cut), said=[], readings=[], last_sure=None)
        rest = []
    return {"say": say, "heard": " ".join(hold["spoken"]), "pending": " ".join(rest), "face": True}


def finish(hold):
    """The button was released: read the window one last time, and say what is left."""
    frames, landmarks = window(hold)
    reading = read(frames, landmarks) if len(frames) >= lp.MIN_FRAMES else None
    if reading is None:
        return []
    words, score = reading
    rest = after(hold["said"], words)
    if hold["spoken"]:  # words were said already: what follows must be sure, not made up from a still mouth
        if score < CONFIDENT or hold["last_sure"] is None:
            return []
        rest = common_start([rest, after(hold["said"], hold["last_sure"])])
    hold["said"] += rest
    hold["spoken"] += rest
    return rest


def frames_so_far(hold):
    """Every frame of the hold, at 25 fps (RGB): for emotion.py and for saving the clip."""
    return window(hold, first=0)[0]


def save(hold, path):
    """Keep the hold as a video, like the recorded clips: test material for lip reading."""
    frames = frames_so_far(hold)
    if not frames:
        return
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), lp.FPS, (w, h))
    for frame in frames:
        if frame.shape[:2] == (h, w):
            out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    out.release()


def replay(clip):
    """Feed a recorded clip in frame by frame, as if live. Returns [(seconds into the clip, words)]."""
    hold = start()
    said = []
    for i, frame in enumerate(lp.read_frames(clip)):
        jpeg = cv2.imencode(".jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1]
        add_frame(hold, struct.pack("<d", i * 1000 / lp.FPS) + jpeg.tobytes())
        if due(hold):
            words = step(hold)["say"]
            if words:
                said.append((i / lp.FPS, words))
    words = finish(hold)
    if words:
        said.append(("release", words))
    return said


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start_time = time.perf_counter()
        said = replay(clip)
        heard = ", ".join(f"{t if isinstance(t, str) else f'{t:.1f}s'}: {' '.join(w)!r}" for t, w in said)
        print(f"{clip}: {heard or 'nothing'} ({time.perf_counter() - start_time:.1f}s)")
