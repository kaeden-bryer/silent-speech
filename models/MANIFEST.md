# Models

Everything runs locally on the Ascent. Fetch these while you have internet; the server needs none afterwards.

| What | Where | Version |
|---|---|---|
| Auto-AVSR code | `third_party/auto_avsr` | `git clone https://github.com/mpc001/auto_avsr`, commit `182b62837773ab01052d4ac21ef1d2203ea7d267` |
| VSR checkpoint | `models/vsr_trlrs2lrs3vox2avsp_base.pth` | LRS3 WER 20.3 %, md5 `49f770f2c0d8b8d769347ee47ed1648f`. `gdown 1r1kx7l9sWnDOCnaFHIGvOtzuhFyFA88_ -O models/vsr_trlrs2lrs3vox2avsp_base.pth` |
| Face detector | `models/blaze_face_short_range.tflite` | `curl -L -o models/blaze_face_short_range.tflite https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite` |
| TTS | Hugging Face cache (`~/.cache/huggingface`) | `hexgrad/Kokoro-82M`, voice `af_heart`. Cached by the first `import tts` |
| Facial expression (emotion.py) | `models/enet_b0_8_best_vgaf.onnx` | HSEmotion EfficientNet-B0, AffectNet 8 classes, 16 MB, sha256 `fa07e841fd06c7a6…`. `curl -L -o models/enet_b0_8_best_vgaf.onnx https://github.com/HSE-asavchenko/face-emotion-recognition/raw/main/models/affectnet_emotions/onnx/enet_b0_8_best_vgaf.onnx` |
| Call captions (Whisper) | Hugging Face cache (`~/.cache/huggingface`) | `distil-whisper/distil-small.en`. Cached by the first `import stt` (`python backend/stt.py clip.wav`). Bigger: `STT_MODEL=openai/whisper-small.en` |
| Sentence fixer (LLM) | Hugging Face cache (`~/.cache/huggingface`) | `Qwen/Qwen3-4B-Instruct-2507`, 8 GB. Cached by the first `python backend/llm_correction.py "hello"` |

## Setup (from the repo root)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install -r backend/requirements.txt gdown   # check `python -c "import torch; print(torch.__version__)"` still ends in +cu130
# then the three downloads above
```

Tested with torch 2.14.1+cu130, mediapipe 1.1.1, kokoro 0.9.4.

## Gotchas

- mediapipe 1.x dropped `mp.solutions`, so the repo's own `detector.py` doesn't work. `lipreading.py` uses the Tasks `FaceDetector` instead (same 4 keypoints).
- torch 2.14 tries to compile some ops with Triton, which needs `python3-dev`. Both model files set `TORCH_DISABLE_NATIVE_JIT=1` to skip that.
- Offline: `export HF_HUB_OFFLINE=1` once Kokoro is cached.
- Call captions use transformers' Whisper, not faster-whisper: CTranslate2 has no aarch64 CUDA build.
