# Baseline harness and scoring: results report (batch 1)

Date: 2026-10-24. Everything below was measured on this machine. **There is no accuracy number
in this report**: no labelled clips have been authorised yet, and nothing here was
fabricated. The one set of clips that was run is synthetic (a still public-domain photo), so
its latency numbers describe the pipeline's cost, not real recordings.

## Environment (verified)

- GPU: NVIDIA GB10, compute capability (12, 1), driver 580.178.04.
- Python env: `/home/asus/Github/silent-speech/.venv`, torch 2.14.1+cu130, arch list up to `sm_120`.
- Inference runs on `cuda:0` through the repo's own `lipreading.py` import.
- The running uvicorn (pid 260728, from the other checkout) was still up afterwards and nothing
  in the shared checkout was modified (its git status shows only the teammate's untracked files).
- `jiwer` was not installed: WER/CER use `rapidfuzz.distance.Levenshtein`, already in the venv.
- Run with `PYTHONDONTWRITEBYTECODE=1`: `third_party/auto_avsr` here is a symlink into the shared checkout.
- Gotcha found: importing `torch` before `lipreading` makes `TORCH_DISABLE_NATIVE_JIT` take effect
  too late, and the first GPU decode then dies in a Triton compile (no `python3-dev`). Import
  `lipreading` first, or set the variable yourself. The scripts and tests here do.

## What was built

| File | Purpose |
|---|---|
| `backend/lipreading.py` | `lip_read_detailed`, `score_candidates`, `score_token_sequences`, `save_roi_debug`; `lip_read`, `decode`, `find_face`, `read_frames` keep their signatures |
| `eval/evaluate.py` | manifest-driven evaluation; writes `predictions.jsonl`, `per_clip.csv`, `summary.json`, `summary.md` |
| `eval/vsr_metrics.py` | normalisation, WER/CER, manifest validation (no torch) |
| `eval/make_smoke_clips.py` | synthetic clips + manifest for checking the machinery |
| `eval/tests/` | 30 unit tests (14 metrics, 16 model-level) |
| `eval/run_vsr.py` | untouched; it reads `~/sihyeon/data` and has an empty `truth` column. Superseded by `evaluate.py`, not run |

Manifest: `video_path,text,category`. Tags joined by `+`: `silent|audible` and
`predefined|unseen|no_speech`. An empty `text` on a speech row means unlabelled: the clip runs
(latency, n-best) but is excluded from accuracy. Clips under `~/sihyeon/data` are refused unless
`--authorized-data` is passed. Reports are per group: ALL, each tag, each full category.

Reported per group: corpus-level WER and CER, exact match, S/D/I counts, oracle n-best WER (best
of the 10 hypotheses per clip: the headroom for rescoring), failed clips, no-speech false-alarm
rate; optionally the same after `correction.correct` (`--with-correction`). Latency per stage
with mean/p50/p95/max, plus real-time factor.

## Measured: tests

`python -m unittest discover -s eval/tests`: **30 tests, all pass** (about 2 s, real model on GPU).

## Measured: candidate scoring against the source

Test clip: 50 frames of one still face (not speech).

- Re-scoring a hypothesis's own token ids reproduces the beam search's numbers: for the top 5
  hypotheses, decoder log-prob and CTC log-prob matched to 4 decimals (e.g. -13.0256 / -29.3556).
- Decoder score agrees with an independent step-by-step `forward_one_step` loop (3 places).
- CTC score agrees with an independent numpy CTC forward algorithm (2 places).
- Batching candidates (padding) does not change scores (3 places).
- The CTC score the beam reports for a finished hypothesis is the full-sequence CTC likelihood,
  so it is directly comparable with `F.ctc_loss` on the same tokens.
- The tokenizer's vocabulary is uppercase: `tokenize("hello how are you")` yields `<unk>` pieces,
  `tokenize("HELLO HOW ARE YOU")` does not. `score_candidates` normalises and uppercases.
- Scores are sums, so a candidate repeated twice scores lower than once (tested), which is why the
  comparability rules in the `lipreading.py` comment block matter: same length, or per-token, or
  relative to the free decode of the same clip; never across clips.
- **Not calibrated.** `score = 0.9*decoder + 0.1*ctc` is a weighted product of two models, so
  `exp(score)` is not a probability. Calibration needs labelled clips.

## Measured: preprocessing (one face, so weak evidence)

On the scikit-image astronaut photo (face is 18.6% of frame width, detector score 0.92):

- BlazeFace keypoint order matches what the repo expects: point 0 (subject's right eye) is on the
  image's left, nose below the eyes, mouth below the nose.
- The mouth crop is centred on the mouth and the 88x88 centre box covers it (`eval` contact sheet via
  `--debug-roi-dir`; I looked at one).
- Fit of the 4 BlazeFace keypoints to the repo's mean-face reference (a dlib-landmark-based layout), after the repo's
  own similarity transform, in the 256 px frame: mouth 0.9 px, right eye 6.1 px, left eye 6.3 px,
  nose 8.6 px. Mapped inter-eye distance 62.9 px against 54.3 px in the reference.
  So BlazeFace's eye and nose points do not sit where the reference expects them; the mouth is
  pinned by the fit. Whether this costs accuracy is **not known**; it needs the baseline below.
- The detector was not replaced.

## Measured: harness smoke run (synthetic, mechanics only)

5 clips from `make_smoke_clips.py`: two still-face clips (2 s, 3 s) tagged `no_speech`, one black
clip (no face), one 5-frame clip, one unlabelled still-face clip. Second run, model warm:

| stage | mean ms | p50 | p95 | max |
|---|---|---|---|---|
| read | 46 | 53 | 78 | 84 |
| face detect | 153 | 148 | 196 | 203 |
| ROI crop+transform | 15 | 14 | 19 | 19 |
| encode | 27 | 29 | 37 | 38 |
| beam search (beam 10) | 222 | 237 | 248 | 249 |
| total | 328 | 430 | 568 | 594 |

Real-time factor 0.16 mean (0.23 p95). The black clip (no face) and the 5-frame clip exit early
and are included in these means. Facts from the run:

- The black clip was reported `face_not_found` (100% missing) and the short clip `too_short`; neither crashed.
- **Both still-face `no_speech` clips produced fluent text** ("we're going to talk about the"): a
  no-speech false-alarm rate of 2/2 on those clips. The free decode never abstains, and uniform
  noise did the same earlier ("i'm going to tell you a little bit about the"). This is the
  motivation for a rejection gate; this evidence is two clips of one still image.
- That text has an n-best margin of 0.21 (top-2 score gap) on the 2 s clip. One sample says
  nothing about whether the margin separates real from empty speech.

## Limitations of this implementation

- `lip_read_detailed` returns failures in `.reason`/`.error`; `lip_read` re-raises the original
  exception, so the server sees the same behaviour as before (and `""` for too-short clips).
  A beam search that returns no hypothesis now gives `""` instead of an `IndexError`.
- `encoder_out` stays on the GPU inside the result; keep the result only as long as you need to rescore.
- Candidate scoring assumes one clip's encoder output; there is no cross-clip normalisation.
- The mouth-jitter statistic is raw BlazeFace keypoint motion over inter-eye distance (median,
  frame to frame); it has no threshold yet.
- `normalize_text` leaves digits as digits ("2" vs "two" counts as an error).
- The 1-face ROI check above is not a statistical statement about BlazeFace.
- The shared checkout's `backend/lipreading.py` is the old version: the running server does not
  have any of this until the file is copied or merged there.

## Unknowns that need real clips

1. Silent-mouthing WER/CER, exact match, and failure rate (the main unknown).
2. Audible vs silent gap for the same speaker (needs both subsets).
3. Whether BlazeFace's eye/nose offset hurts accuracy (compare detectors only on a baseline).
4. Whether n-best margin, per-token score, or constrained-vs-free score separates correct
   clips from wrong ones and from no-speech (needs labelled clips including `no_speech`).
5. Latency with real 3-5 s clips and a webm/mp4 decode path (the smoke clips are MJPG AVI).
6. Maximum clip length the model handles before quality degrades.
7. How often the fuzzy matcher wrongly snaps unseen sentences (`--with-correction`, `unseen` group).

## Recommended next experiments

1. **Collect a small labelled set** (suggest 20-30 clips: 10 predefined, 10 unseen, 5 no_speech, each
   silent; plus audible versions for a few) and write the manifest. Then run
   `python eval/evaluate.py manifest.csv --with-correction --debug-roi-dir eval/debug_roi`.
   Authorise `~/sihyeon/data` explicitly if those 27 clips should be used (they need transcripts).
2. With that run: check oracle n-best WER against WER (rescoring headroom), then
   `score_candidates` on the 8 phrases + the truth for the same clips (is the right phrase ranked first?).
3. Compare beam 10 vs 40 (`BEAM_SIZE` in `lipreading.py`) on the same set.
4. Only if the ROI contact sheets or WER look bad: try the repo's own detector path as a controlled A/B.
5. Fit a threshold/calibration on the labelled set for a confidence gate, keeping model scores and
   calibrated confidence as separate fields.
