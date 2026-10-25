"""Track 2: lip reading.

Input:  path to a short video of someone mouthing one sentence
        (.webm from Chrome/Android, .mp4 from iPhone, no sound)
Output: the text they said. Mistakes are fine, correction.py fixes them.

How: Auto-AVSR (third_party/auto_avsr), using its own mouth cropping and transforms.
MediaPipe finds the eyes, nose and mouth in every frame, the face is aligned to a
mean face, and a 96x96 mouth patch is cut out. The model is loaded once, at import.
Setup: models/MANIFEST.md.  Try a clip on its own:  python lipreading.py clip.webm

lip_read(path) -> str is the interface the server uses. lip_read_detailed(path) returns the
same text plus n-best hypotheses, model scores, face statistics and per-stage timings, and
score_candidates(result, texts) scores given sentences against the video. Those scores are
raw model log-likelihoods, NOT calibrated confidences: see the notes above score_candidates.
"""

import os
import queue
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

# torch 2.14 compiles some ops with Triton on first use, which needs python3-dev headers.
# Plain CUDA kernels are fine here. Must be set before torch is imported.
os.environ.setdefault("TORCH_DISABLE_NATIVE_JIT", "1")

import cv2
import mediapipe as mp
import numpy as np
import torch
import torch.nn.functional as F
from mediapipe.tasks.python import BaseOptions, vision

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "third_party" / "auto_avsr"))
from datamodule.transforms import TextTransform, VideoTransform  # noqa: E402
from espnet.nets.batch_beam_search import BatchBeamSearch  # noqa: E402
from espnet.nets.pytorch_backend.e2e_asr_conformer import E2E  # noqa: E402
from espnet.nets.pytorch_backend.transformer.mask import subsequent_mask  # noqa: E402
from preparation.detectors.mediapipe.video_process import VideoProcess  # noqa: E402

CHECKPOINT = ROOT / "models" / "vsr_trlrs2lrs3vox2avsp_base.pth"
FACE_MODEL = ROOT / "models" / "blaze_face_short_range.tflite"
DEVICE = "cuda"
FPS = 25  # the model was trained on 25 fps video
BEAM_SIZE = 10  # the repo uses 40: slightly better, slower
MIN_FRAMES = 10  # shorter than ~0.4 s: nothing was said
MAX_MISSING = 0.3  # give up if the face is missing in more frames than this
DECODER_WEIGHT, CTC_WEIGHT = 0.9, 0.1  # hybrid CTC/attention weights, as in the repo's eval
NBEST_KEEP = 10  # hypotheses returned by lip_read_detailed
FACE_THREADS = 8  # frames searched for the face at once: ~8x faster than one by one, same result

detectors = queue.SimpleQueue()  # one detector per thread: a detector can't be used by two at once
for _ in range(FACE_THREADS):
    detectors.put(vision.FaceDetector.create_from_options(
        vision.FaceDetectorOptions(base_options=BaseOptions(model_asset_path=str(FACE_MODEL)))
    ))
face_pool = ThreadPoolExecutor(FACE_THREADS)
video_process = VideoProcess(convert_gray=False)
video_transform = VideoTransform(subset="test")
text_transform = TextTransform()

model = E2E(len(text_transform.token_list), "video")
model.load_state_dict(torch.load(CHECKPOINT, map_location="cpu"))
model.to(DEVICE).eval()
beam_search = BatchBeamSearch(
    beam_size=BEAM_SIZE,
    vocab_size=len(text_transform.token_list),
    weights={"decoder": DECODER_WEIGHT, "ctc": CTC_WEIGHT},
    scorers=model.scorers(),
    sos=model.odim - 1,
    eos=model.odim - 1,
    token_list=text_transform.token_list,
    pre_beam_score_key="decoder",
).to(DEVICE).eval()
gpu = threading.Lock()  # one clip at a time




def _read_frames(video_path):
    """RGB frames resampled to 25 fps, plus the container's fps and raw frame count."""
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
    return [frames[i] for i in picks], native_fps, len(frames)


def read_frames(video_path):
    """RGB frames, resampled to 25 fps (phones record at 30 fps or a variable rate)."""
    return _read_frames(video_path)[0]


def _detect(frame):
    """(4 keypoints in pixels or None, faces found, detector score, face width / frame width)."""
    detector = detectors.get()
    try:
        faces = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)).detections
    finally:
        detectors.put(detector)
    if not faces:
        return None, 0, 0.0, 0.0
    face = max(faces, key=lambda f: f.bounding_box.width * f.bounding_box.height)
    h, w = frame.shape[:2]
    points = np.array([[k.x * w, k.y * h] for k in face.keypoints[:4]])
    score = face.categories[0].score if face.categories else 0.0
    return points, len(faces), float(score), face.bounding_box.width / w


def find_face(frame):
    """Right eye, left eye, nose tip, mouth centre in pixels (the 4 points the repo uses), or None."""
    return _detect(frame)[0]


def _search(video):
    """video: T x 1 x 88 x 88 tensor. Caller holds `gpu`. Returns (encoder output T' x 768, n-best)."""
    with torch.no_grad():
        x = model.proj_encoder(model.frontend(video.unsqueeze(0).to(DEVICE)))
        enc, _ = model.encoder(x, None)
        enc = enc.squeeze(0)
        return enc, beam_search(enc)


def _to_text(ids):
    """Token ids (no sos) to lowercase text."""
    ids = torch.tensor([int(i) for i in ids], dtype=torch.long)
    return text_transform.post_process(ids).replace("<eos>", "").strip().lower()


def decode(video):
    """video: T x 1 x 88 x 88 tensor, already transformed. Returns lowercase text."""
    with gpu:
        _, hyps = _search(video)
    return _to_text(hyps[0].yseq[1:]) if hyps else ""


# ---- detailed result ---------------------------------------------------------------


@dataclass
class NBestEntry:
    """One beam-search hypothesis. All scores are natural-log, summed over the sequence."""

    text: str
    token_ids: list  # without sos/eos
    score: float  # the beam's own ranking score: 0.9 * decoder_logprob + 0.1 * ctc_logprob
    decoder_logprob: float  # attention decoder, includes the <eos> token
    ctc_logprob: float  # full-sequence CTC log-likelihood (the CTC prefix score at <eos>)
    n_scored_tokens: int  # len(token_ids) + 1: what decoder_logprob is a sum over

    @property
    def score_per_token(self):
        return self.score / self.n_scored_tokens


@dataclass
class FaceStats:
    n_frames_raw: int = 0  # frames in the file
    native_fps: float = 0.0
    n_frames: int = 0  # frames after resampling to 25 fps (what the model sees)
    duration_s: float = 0.0
    n_detected: int = 0
    missing_frac: float = 0.0
    n_multi_face_frames: int = 0  # frames where the detector found more than one face
    mean_det_score: float = 0.0  # BlazeFace score of the chosen face, over detected frames
    mean_face_width_frac: float = 0.0  # chosen face width / frame width
    # median frame-to-frame motion of the mouth keypoint, in inter-eye distances. A talking
    # mouth moves a bit; a large value on a still face means the detector is jittering.
    mouth_jitter: float = 0.0


@dataclass
class LipReadResult:
    raw_text: str = ""
    nbest: list = field(default_factory=list)  # NBestEntry, best first
    frames: FaceStats = field(default_factory=FaceStats)
    timings_ms: dict = field(default_factory=dict)
    n_enc_frames: int = 0
    reason: str = "ok"  # ok | too_short | face_not_found | no_hypothesis | error
    error: str | None = None
    encoder_out: object = field(default=None, repr=False, compare=False)  # T' x 768, on the GPU
    exception: object = field(default=None, repr=False, compare=False)

    @property
    def nbest_margin(self):
        """Score gap between the best and second-best hypothesis (None with fewer than two)."""
        return self.nbest[0].score - self.nbest[1].score if len(self.nbest) > 1 else None

    def to_dict(self):
        """JSON-friendly (no tensors)."""
        out = {
            "raw_text": self.raw_text,
            "reason": self.reason,
            "error": self.error,
            "nbest": [dict(asdict(h), score_per_token=h.score_per_token) for h in self.nbest],
            "nbest_margin": self.nbest_margin,
            "frames": asdict(self.frames),
            "n_enc_frames": self.n_enc_frames,
            "timings_ms": self.timings_ms,
        }
        return out


class FaceNotFound(ValueError):
    pass


@contextmanager
def _timed(timings, name):
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = (time.perf_counter() - start) * 1000


def _face_stats(frames, detections, native_fps, n_raw):
    stats = FaceStats(n_frames_raw=n_raw, native_fps=float(native_fps), n_frames=len(frames))
    stats.duration_s = len(frames) / FPS
    found = [d for d in detections if d[0] is not None]
    stats.n_detected = len(found)
    stats.missing_frac = 1 - len(found) / len(frames)
    stats.n_multi_face_frames = sum(d[1] > 1 for d in detections)
    if found:
        stats.mean_det_score = float(np.mean([d[2] for d in found]))
        stats.mean_face_width_frac = float(np.mean([d[3] for d in found]))
    steps = []
    for a, b in zip(detections, detections[1:]):
        if a[0] is not None and b[0] is not None:
            eye_dist = np.linalg.norm(a[0][0] - a[0][1]) or 1.0
            steps.append(np.linalg.norm(b[0][3] - a[0][3]) / eye_dist)
    stats.mouth_jitter = float(np.median(steps)) if steps else 0.0
    return stats


def save_roi_debug(frames, landmarks, mouth, video, out_prefix, n=16):
    """Write <out_prefix>_roi.png for eyeballing the crop. Local files only, nothing is sent anywhere.

    Top: the first frame with a detection, with the 4 keypoints (0 right eye, 1 left eye,
    2 nose, 3 mouth centre; "right" is the subject's right, so it sits on the image's left).
    Middle: n evenly spaced 96x96 crops with the 88x88 centre box the model sees.
    Bottom: those frames as the model receives them (88x88 grayscale, normalisation undone).
    """
    first = next((i for i, lm in enumerate(landmarks) if lm is not None), 0)
    top = cv2.cvtColor(frames[first], cv2.COLOR_RGB2BGR).copy()
    scale = 256 / top.shape[0]
    top = cv2.resize(top, None, fx=scale, fy=scale)
    if landmarks[first] is not None:
        for k, (x, y) in enumerate(landmarks[first] * scale):
            cv2.circle(top, (int(x), int(y)), 3, (0, 255, 0), -1)
            cv2.putText(top, str(k), (int(x) + 4, int(y) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    picks = np.linspace(0, len(mouth) - 1, min(n, len(mouth))).astype(int)
    crops, gray = [], []
    for i in picks:
        crop = cv2.cvtColor(np.ascontiguousarray(mouth[i]), cv2.COLOR_RGB2BGR)
        cv2.rectangle(crop, (4, 4), (91, 91), (0, 0, 255), 1)
        cv2.putText(crop, str(i), (2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        crops.append(crop)
        g = (video[i, 0].numpy() * 0.165 + 0.421).clip(0, 1) * 255
        gray.append(cv2.copyMakeBorder(cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR), 4, 4, 4, 4, cv2.BORDER_CONSTANT))
    width = 96 * len(crops)
    pad = lambda img, h=None: cv2.copyMakeBorder(img, 0, 0, 0, max(0, width - img.shape[1]), cv2.BORDER_CONSTANT)
    sheet = np.vstack([pad(top), pad(np.hstack(crops)), pad(np.hstack(gray))])
    out = Path(f"{out_prefix}_roi.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet)
    return out


def lip_read_detailed(video_path: str, debug_dir: str | None = None, nbest: int = NBEST_KEEP) -> LipReadResult:
    """Like lip_read, but returns a LipReadResult instead of raising.

    Failures are reported in .reason / .error (and the exception in .exception) with whatever
    statistics were gathered before the failure. debug_dir: also write a local ROI image there.
    """
    result = LipReadResult()
    timings = result.timings_ms
    total = time.perf_counter()
    try:
        with _timed(timings, "read_ms"):
            frames, native_fps, n_raw = _read_frames(video_path)
        result.frames = FaceStats(n_frames_raw=n_raw, native_fps=float(native_fps), n_frames=len(frames),
                                  duration_s=len(frames) / FPS)
        if len(frames) < MIN_FRAMES:
            result.reason = "too_short"
            return result
        with _timed(timings, "detect_ms"):
            detections = list(face_pool.map(_detect, frames))
        result.frames = _face_stats(frames, detections, native_fps, n_raw)
        if result.frames.missing_frac > MAX_MISSING:
            raise FaceNotFound(f"face not found in {result.frames.missing_frac:.0%} of frames")
        landmarks = [d[0] for d in detections]
        raw_landmarks = list(landmarks)  # video_process fills gaps in place
        with _timed(timings, "roi_ms"):
            mouth = video_process(np.stack(frames), landmarks)  # T x 96 x 96 x 3
            video = video_transform(torch.tensor(mouth).permute(0, 3, 1, 2))
        if debug_dir:
            try:
                save_roi_debug(frames, raw_landmarks, mouth, video, Path(debug_dir) / Path(video_path).stem)
            except Exception as e:  # a debug picture must never break recognition
                print(f"ROI debug image failed: {e}", file=sys.stderr)
        with gpu:
            with _timed(timings, "encode_ms"):
                with torch.no_grad():
                    x = model.proj_encoder(model.frontend(video.unsqueeze(0).to(DEVICE)))
                    enc, _ = model.encoder(x, None)
                    enc = enc.squeeze(0)
                    torch.cuda.synchronize()
            with _timed(timings, "beam_ms"):
                with torch.no_grad():
                    hyps = beam_search(enc)
        result.encoder_out, result.n_enc_frames = enc, enc.size(0)
        for h in hyps[:nbest]:
            ids = [int(i) for i in h.yseq[1:]]
            if ids and ids[-1] == model.odim - 1:  # strip <eos>
                ids = ids[:-1]
            result.nbest.append(NBestEntry(
                text=_to_text(ids), token_ids=ids, score=float(h.score),
                decoder_logprob=float(h.scores["decoder"]), ctc_logprob=float(h.scores["ctc"]),
                n_scored_tokens=len(ids) + 1,
            ))
        if result.nbest:
            result.raw_text = result.nbest[0].text
        else:
            result.reason = "no_hypothesis"
    except Exception as e:
        result.reason = "face_not_found" if isinstance(e, FaceNotFound) else "error"
        result.error, result.exception = f"{type(e).__name__}: {e}", e
    finally:
        timings["total_ms"] = (time.perf_counter() - total) * 1000
    return result


def lip_read(video_path: str) -> str:
    result = lip_read_detailed(video_path)
    if result.exception is not None:  # same exceptions as before the detailed interface existed
        raise result.exception
    return result.raw_text


# ---- scoring given sentences against a video ----------------------------------------
#
# What the numbers are. For a candidate sentence y and the encoder output of a clip:
#   decoder_logprob = sum_t log p_att(y_t | y_<t, video) over the tokens of y plus <eos>
#                     (teacher forcing: the same quantity beam search accumulates per hypothesis)
#   ctc_logprob     = log of the CTC likelihood of y over all alignments (no <eos> term)
#   score           = 0.9 * decoder_logprob + 0.1 * ctc_logprob, the beam search's ranking score
# Each is the log of a probability under one model, but `score` is a weighted product of two
# models, so exp(score) is not a probability. Nothing here is calibrated: do not read it as the
# chance that the sentence is right. Calibration needs labelled clips (see eval/).
#
# Comparability. Scores are sums over tokens, so longer candidates are penalised:
#   * comparing candidates of the same clip with the same length: `score` is fine;
#   * comparing candidates of different length: prefer `score_per_token`, which is a crude fix
#     (it favours long sentences made of easy tokens), or compare against the free decode's
#     score with the same normalisation (LipReadResult.nbest[0]);
#   * never compare scores across clips: the clip's length and difficulty are in the number.
# The CTC term is not length-normalised by frame count either; it is only meaningful relative
# to other candidates (or the free decode) for the same clip.


def normalize_for_scoring(text):
    """Uppercase, keep letters, digits and apostrophes, collapse spaces (the vocabulary is
    uppercase LRS3-style text: lowercase words tokenize to <unk>)."""
    text = text.replace("’", "'").upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9' ]", " ", text)).strip()


def tokenize_for_scoring(text):
    """Token ids of normalize_for_scoring(text), using the model's own tokenizer."""
    norm = normalize_for_scoring(text)
    return [int(i) for i in text_transform.tokenize(norm)] if norm else []


@dataclass
class CandidateScore:
    text: str
    normalized: str
    token_ids: list
    unk_count: int  # tokens the tokenizer could not map: a high count makes the score unreliable
    n_scored_tokens: int
    decoder_logprob: float
    ctc_logprob: float
    score: float
    valid: bool  # False for empty candidates (scores are -inf)

    @property
    def score_per_token(self):
        return self.score / self.n_scored_tokens if self.valid else float("-inf")


def score_token_sequences(enc, sequences):
    """Score token-id sequences (no sos/eos) against encoder output enc (T' x 768).

    Returns (decoder_logprobs, ctc_logprobs) as float lists. One batched decoder pass and one
    CTC call, whatever the number of sequences; the encoder is not re-run.
    """
    with gpu, torch.no_grad():
        enc = enc.to(DEVICE)
        n, steps = len(sequences), enc.size(0)
        sos = eos = model.odim - 1
        width = max(len(s) for s in sequences) + 1
        ys_in = torch.full((n, width), eos, dtype=torch.long, device=DEVICE)
        ys_out = torch.full((n, width), -1, dtype=torch.long, device=DEVICE)
        for i, seq in enumerate(sequences):
            ys_in[i, 0] = sos
            ys_in[i, 1 : len(seq) + 1] = torch.tensor(seq, dtype=torch.long)
            ys_out[i, : len(seq)] = torch.tensor(seq, dtype=torch.long)
            ys_out[i, len(seq)] = eos
        # causal mask: positions after a sequence's end are padding and cannot affect earlier ones
        logits, _ = model.decoder(ys_in, subsequent_mask(width, device=DEVICE).unsqueeze(0),
                                  enc.unsqueeze(0).expand(n, -1, -1), None)
        token_logp = logits.log_softmax(-1).gather(-1, ys_out.clamp(min=0).unsqueeze(-1)).squeeze(-1)
        decoder_logp = (token_logp * (ys_out >= 0)).sum(1)

        frame_logp = model.ctc.log_softmax(enc.unsqueeze(0)).float().transpose(0, 1)  # T' x 1 x V
        targets = torch.tensor([t for seq in sequences for t in seq], dtype=torch.long, device=DEVICE)
        ctc_nll = F.ctc_loss(
            frame_logp.expand(-1, n, -1).contiguous(), targets,
            torch.full((n,), steps, dtype=torch.long), torch.tensor([len(s) for s in sequences]),
            blank=0, reduction="none", zero_infinity=False,
        )
        return decoder_logp.tolist(), (-ctc_nll).tolist()


def score_candidates(source, texts):
    """Score sentences against a clip. source: a LipReadResult from lip_read_detailed (its
    encoder output is reused) or an encoder-output tensor. Returns one CandidateScore per text,
    in order. See the notes above for what the scores mean and how to compare them."""
    enc = source.encoder_out if isinstance(source, LipReadResult) else source
    if enc is None:
        raise ValueError("no encoder output: the clip did not reach the model")
    unk = text_transform.hashmap["<unk>"]
    prepared = [(t, normalize_for_scoring(t), tokenize_for_scoring(t)) for t in texts]
    todo = [i for i, (_, _, ids) in enumerate(prepared) if ids]
    scored = {}
    if todo:
        dec, ctc = score_token_sequences(enc, [prepared[i][2] for i in todo])
        scored = {i: (d, c) for i, d, c in zip(todo, dec, ctc)}
    out = []
    for i, (text, norm, ids) in enumerate(prepared):
        d, c = scored.get(i, (float("-inf"), float("-inf")))
        out.append(CandidateScore(
            text=text, normalized=norm, token_ids=ids, unk_count=sum(t == int(unk) for t in ids),
            n_scored_tokens=len(ids) + 1, decoder_logprob=d, ctc_logprob=c,
            score=DECODER_WEIGHT * d + CTC_WEIGHT * c, valid=bool(ids),
        ))
    return out


decode(torch.randn(50, 1, 88, 88))  # warm-up: the first GPU run is slow


if __name__ == "__main__":
    for clip in sys.argv[1:]:
        start = time.perf_counter()
        text = lip_read(clip)
        print(f"{clip}: {text!r} ({time.perf_counter() - start:.2f}s)")
