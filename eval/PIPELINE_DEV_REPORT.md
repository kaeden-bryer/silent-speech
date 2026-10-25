# Frozen pipeline: DEV performance and latency report

Strategy (frozen, `eval/frozen_config.json`): Auto-AVSR (beam 10) -> visual phrase gate (margin per token >= 1.0) -> Qwen2.5-1.5B-Instruct
likelihood fusion (lambda 0.5) -> final text. Dev split only (22 clips, one speaker); the held-out test split has not been run.
Numbers were produced by `eval/bench_pipeline.py` on 2026-10-24 on the ASUS GX10 (NVIDIA GB10, torch 2.14.1+cu130). 17 silent clips is a small
sample: the confidence interval on every accuracy number is wide.

# Frozen hybrid on the DEV cache

Config `phase3-1:b3b11ea05a921c8f`: visual phrase gate (margin per token >= 1.0) -> Qwen likelihood fusion (lambda = 0.5) -> final text. Computed by `pipeline.choose` (production code) from the Phase 1/2 cached scores; lambda and the gate threshold were fixed in advance and not revisited after seeing these numbers.

| | silent WER | silent CER | silent exact | predefined (8) | unseen+contrast (9) | unseen only (5) | audible exact (3) | all scored WER (20) |
|---|---|---|---|---|---|---|---|---|
| A raw Auto-AVSR | 41.5% | 32.1% | 5/17 | 3/8 (WER 41.4%) | 2/9 (WER 41.5%) | 1/5 | 0/3 | 50.5% |
| B visual gate only | 32.9% | 26.4% | 8/17 | 6/8 (WER 17.2%) | 2/9 (WER 41.5%) | 1/5 | 2/3 | 34.7% |
| **H hybrid (gate + LM fusion, lambda 0.5)** | 28.0% | 21.5% | 10/17 | 6/8 (WER 27.6%) | 4/9 (WER 28.3%) | 2/5 | 2/3 | 31.6% |

Exact numbers for H on the 17 silent clips: 23 word errors / 82 reference words = WER 28.05%, CER 21.54%, exact 10/17. On all 20 scored clips (incl. audible): WER 31.58%, CER 24.34%, exact 12/20.
Paired against A on the silent clips: -13.4 points (bootstrap 95% interval -29.8 to +1.2); 6 clips better, 2 worse, 9 unchanged. Wrong predefined phrase on a non-phrase sentence: 0; phrase on a no-speech clip: 0.

Reproducibility: the Phase 2 analysis reported E B + C2 lam=0.5 at silent WER 28.0%, exact 10/17. This run: 28.0%, 10/17.

## Which path each dev clip took

| clip | truth | raw | final | method | needs confirmation | result |
|---|---|---|---|---|---|---|
| contrast01a | I can come to the meeting. | i can come to the meeting | i can come to the meeting | lm_fusion | True | exact |
| pre03_t1 | Thank you very much. | thank you very much | Thank you very much. | visual_gate | False | exact |
| uns03 | My phone is on the table. | my phone is on the table | my phone is on the table | lm_fusion | True | exact |
| contrast02a | Please turn the lights on. | please turn the grandson | please turn the lights on | lm_fusion | True | exact |
| uns02 | I would like a glass of water. | i really like a glass of water | i would like a glass of water | lm_fusion | True | exact |
| pre02_t1 | Nice to meet you. | i still meet you | Nice to meet you. | visual_gate | True | exact |
| pre07_t1 | Let's win Calhacks! | alright sweet nowadays | all right sweet all right | lm_fusion | True | 5 word errors |
| contrast01b | I cannot come to the meeting. | i did not come to the meeting | i did not come to the meeting | lm_fusion | True | 2 word errors |
| uns05 | Please turn left at the corner. | but is her life like the lord | but is her life like the lord | lm_fusion | True | 6 word errors |
| nos01 | (none) | i'm going to tell you a little bit | i'm going to tell you a little bit | lm_fusion | True | no speech |
| contrast02b | Please turn the lights off. | but it's not the last time | but it's not the last time | lm_fusion | True | 5 word errors |
| pre08_t1 | I need more caffeine. | i need more coffee | I need more caffeine. | visual_gate | True | exact |
| pre06_t1 | Testing silent speech. | that's exactly speech | that's exactly the speech | lm_fusion | True | 3 word errors |
| nos02 | (none) | i've been working with a lot of pe | i've been working with a lot of pe | lm_fusion | True | no speech |
| pre04_t1 | What is your name? | what is your name | What is your name? | visual_gate | False | exact |
| uns04 | What time does the store close? | one time there's a door closed | what time does the door close | lm_fusion | True | 1 word errors |
| pre05_t1 | See you later. | a single and her | See you later. | visual_gate | True | exact |
| pre01_t1 | Hello, how are you? | hello how are you | Hello, how are you? | visual_gate | False | exact |
| uns01 | Could you open the window please? | can you open the window please | can you open the window please | lm_fusion | True | 1 word errors |
| aud01 | Hello, how are you? | i don't know how i do | Hello, how are you? | visual_gate | True | exact |
| aud02 | See you later. | a single idea | See you later. | visual_gate | True | exact |
| aud03 | Could you open the window please? | and interpret the rest of it | get a job with a great company | lm_fusion | True | 7 word errors |

Paths: 8 visual gate, 14 LM fusion (the LM runs only on those). needs_confirmation=False for 3 clips (pre03_t1, pre04_t1, pre01_t1); every one of them exact: True.

## Regression and improvement cases vs raw (A)

| clip | truth | raw | hybrid | word errors raw -> hybrid | verdict |
|---|---|---|---|---|---|
| contrast02a | Please turn the lights on. | please turn the grandson | please turn the lights on | 2 -> 0 | IMPROVED |
| uns02 | I would like a glass of water. | i really like a glass of water | i would like a glass of water | 1 -> 0 | IMPROVED |
| pre02_t1 | Nice to meet you. | i still meet you | Nice to meet you. | 2 -> 0 | IMPROVED |
| pre07_t1 | Let's win Calhacks! | alright sweet nowadays | all right sweet all right | 3 -> 5 | REGRESSION |
| pre08_t1 | I need more caffeine. | i need more coffee | I need more caffeine. | 1 -> 0 | IMPROVED |
| pre06_t1 | Testing silent speech. | that's exactly speech | that's exactly the speech | 2 -> 3 | REGRESSION |
| uns04 | What time does the store close? | one time there's a door closed | what time does the door close | 5 -> 1 | IMPROVED |
| pre05_t1 | See you later. | a single and her | See you later. | 4 -> 0 | IMPROVED |
| aud01 | Hello, how are you? | i don't know how i do | Hello, how are you? | 5 -> 0 | IMPROVED |
| aud02 | See you later. | a single idea | See you later. | 3 -> 0 | IMPROVED |
| aud03 | Could you open the window please? | and interpret the rest of it | get a job with a great company | 6 -> 7 | REGRESSION |

## Compared with the visual gate alone (B): what the LM fusion added

| clip | truth | gate only | hybrid | word errors gate only -> hybrid | verdict |
|---|---|---|---|---|---|
| contrast02a | Please turn the lights on. | please turn the grandson | please turn the lights on | 2 -> 0 | IMPROVED |
| uns02 | I would like a glass of water. | i really like a glass of water | i would like a glass of water | 1 -> 0 | IMPROVED |
| pre07_t1 | Let's win Calhacks! | alright sweet nowadays | all right sweet all right | 3 -> 5 | REGRESSION |
| pre06_t1 | Testing silent speech. | that's exactly speech | that's exactly the speech | 2 -> 3 | REGRESSION |
| uns04 | What time does the store close? | one time there's a door closed | what time does the door close | 5 -> 1 | IMPROVED |
| aud03 | Could you open the window please? | and interpret the rest of it | get a job with a great company | 6 -> 7 | REGRESSION |


# Live benchmark on the DEV recordings (fresh process, NVIDIA GB10)

## Loading and memory

- Auto-AVSR + MediaPipe + warm-up decode (`import lipreading`): **2.8 s**
- Qwen2.5-1.5B-Instruct (local cache, bf16): **17.4 s**; total pipeline construction 20.2 s (one-off, at start-up)
- GPU memory allocated by this process after loading both models: **3982 MiB**; peak during 44 recognitions: **4614 MiB**
- nvidia-smi for this process: 4500.0 MiB after loading, 6573.0 MiB at the end (includes CUDA context and cache)

## Cold vs warm

First `recognize` call in the process (no pipeline warm-up; Auto-AVSR itself is warmed by its own import) vs the same clip after `warm_up()`:

| stage ms | cold first call | same clip, warm |
|---|---|---|
| read_ms | 62 | 60 |
| detect_ms | 162 | 205 |
| roi_ms | 31 | 30 |
| encode_ms | 19 | 17 |
| beam_ms | 143 | 143 |
| phrase_scoring_ms | 11 | 6 |
| lm_scoring_ms | 236 | 31 |
| routing_overhead_ms | 0 | 0 |
| **whole call** | **666** (lm_fusion) | **496** (lm_fusion) |

## Warm latency over the dev clips (second pass; ms per clip)

| stage | n | mean | median | p95 | max |
|---|---|---|---|---|---|
| video read + resample | 22 | 64 | 56 | 80 | 148 |
| face detection (MediaPipe) | 22 | 273 | 234 | 368 | 795 |
| mouth ROI crop + transform | 22 | 43 | 32 | 71 | 109 |
| Auto-AVSR encoder | 22 | 19 | 17 | 27 | 36 |
| Auto-AVSR beam search (10-best) | 22 | 211 | 150 | 223 | 1039 |
| = Auto-AVSR path total | 22 | 612 | 498 | 662 | 2132 |
| visual gate: score the 8 phrases (encoder reused) | 22 | 6 | 6 | 6 | 8 |
| Qwen likelihood scoring (only when the gate rejects) | 14 | 33 | 32 | 45 | 49 |
| hybrid routing overhead (decision code, excluding Qwen) | 22 | 0 | 0 | 0 | 0 |
| **whole `recognize()` call** | 22 | 640 | 534 | 703 | 2191 |
| (first pass, for comparison) | 22 | 636 | 524 | 737 | 1962 |

By path taken: lm_fusion: n=14, mean 750 ms, max 2191 ms; visual_gate: n=8, mean 446 ms, max 541 ms.

## Consistency

- Two passes gave identical final texts and methods: **True**
- Differences from the cached frozen decision (cache-eval): **0** 
- Live silent WER 28.05%, CER 21.54%, exact 10/17; paths: {'visual_gate': 8, 'lm_fusion': 14}

## Failure and fallback behaviour

- Qwen scoring raises an error (simulated CUDA OOM) on `contrast01a`: method `visual_fallback`, final text equals the raw reading: True, needs_confirmation=True, 419 ms (normal 529 ms). Recovers on the next clip: True.
- Qwen not available at start-up (init 0.43 s, no network): clips are still recognised, method `visual_fallback`, final equals raw: True, 429 ms.
- `black.avi` (no face / too short / unreadable): method `failed`, final text '', reason `face_not_found`, 150 ms.
- `short.avi` (no face / too short / unreadable): method `failed`, final text '', reason `too_short`, 9 ms.
- `missing.avi` (no face / too short / unreadable): method `failed`, final text '', reason `error`, 0 ms.
- Empty demo_phrases.txt (gate disabled): method `lm_fusion`, 491 ms.

