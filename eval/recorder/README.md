# Evaluation recorder

A small local tool for recording the labelled lip-reading evaluation set (40 clips per speaker).
Standalone: it does not touch `backend/` or `frontend/`, and uses its own port (8001). Recordings
are saved under `eval/dataset/` (git-ignored) and go nowhere else: the page loads no external
resources and the server makes no outgoing connections.

The earlier recordings in `~/sihyeon/data/` are not used; the tool refuses that directory.

## The 40 clips (`plan.py`)

| set | clips | what |
|---|---|---|
| predefined | 16 | the 8 phrases of `backend/demo_phrases.txt`, two takes each, silent |
| unseen | 10 | new everyday sentences, silent |
| contrast | 6 | 3 pairs: negation (can / cannot), on / off, bark / park, silent |
| no_speech | 4 | motionless face x2, head movement with mouth closed, non-speech mouth movement; ground truth is `""` |
| audible | 4 | the same sentence spoken aloud, paired with a silent clip (`pair_id` audible01..04) |

**Splits.** `dev` is for building and tuning; `test` is held out. Predefined: take 1 is dev, take 2
is test. Unseen: 5 sentences dev, 5 different sentences test. A contrast pair never straddles the
split. Audible clips inherit the split of their silent partner. 22 clips dev, 18 test.
`evaluate.py` runs **dev only** unless you pass `--split test` or `--split all`. Do not tune
thresholds, prompts or matching rules on test; run it once at the end.

**Labels.** A no-speech clip has `text=""` and `label_status=no_speech`: a labelled empty transcript.
A clip with no known transcript would be `label_status=unlabeled` (this tool never writes one) and
`evaluate.py` runs it without scoring. The parser rejects rows where the two disagree.

## Launch from VS Code Remote SSH (on the laptop)

1. In the VS Code terminal connected to the GX10:
   ```bash
   cd ~/sihyeon/ss-sihyeon
   python3 eval/recorder/server.py
   ```
   It prints `http://localhost:8001/?token=...`. It listens on `127.0.0.1` only, so nothing else on
   the network can reach it. No venv is needed (standard library only).
2. VS Code forwards port 8001 to your laptop automatically (check the **Ports** tab; if it is not
   listed, "Forward a Port" -> 8001). Keep it **Private**; never set a recording port to Public.
3. Open the printed URL in Chrome (or Firefox) **on the laptop**, including the `?token=...`. If the
   Ports tab shows a different local port, use that port with the same token. `localhost` counts as a
   secure context, so the camera works over plain http.
4. Enter a speaker ID (e.g. `spk01`), allow the camera, and follow the prompts.
   Space = record / stop, Enter = save, R = retry, left/right arrows = previous/next clip.
5. Stop the server with Ctrl+C. Restarting resumes where you left off (saved clips show a tick).

Use a different speaker ID for each person; each gets its own folder and manifest.

## From a phone

Phones only allow the camera on HTTPS, and the recorder must be reachable by the phone.

```bash
python3 eval/recorder/server.py --lan
```
This serves HTTPS with a self-signed certificate (made locally in `eval/recorder/.certs/`) on all
interfaces and prints one URL per address. Open one on the phone:
- same Wi-Fi/LAN as the GX10: the `192.168.x.x` URL (this machine's current LAN address is printed);
- phone and GX10 both on Tailscale: the `100.x.x.x` URL. Traffic is WireGuard-encrypted and stays
  within your tailnet.

The browser warns about the certificate; accept it for that address. The token in the URL is required
for every request, so other devices on the network cannot upload or read clips.

Not safe for face video, so avoid: `cloudflared` or any public tunnel (the video would pass through a
third party), VS Code ports set to Public, and `tailscale funnel`.

Not tested here: a phone browser against `--lan` (iOS Safari may need the certificate trusted before
it allows the camera), and a Wi-Fi network that isolates clients (venue/guest Wi-Fi often does).
If the phone cannot connect, use the laptop route.

## What gets written

```
eval/dataset/plan.json                         snapshot of the plan (labels stay stable if plan.py changes)
eval/dataset/<speaker>/clips/<speaker>_<clip_id>_<mode>.webm   (.mp4 from Safari)
eval/dataset/<speaker>/meta/<same name>.json   one per clip: source of truth for the manifest
eval/dataset/<speaker>/manifest.csv            rebuilt after every save
eval/dataset/<speaker>/superseded/             earlier takes replaced by a re-record
eval/dataset/manifest_all.csv                  all speakers
```
Manifest columns: `video_path,text,category,clip_id,speaker_id,speech_mode,split,set,pair_id,take,label_status,mime,bytes,duration_s,attempts,recorded_at`.
`video_path` is relative to the manifest's folder. Nothing is overwritten or deleted: saving the
same clip again requires an explicit re-record, which first moves the old take to `superseded/`. Do
not edit transcripts in the CSV by hand; re-record instead.

## Evaluate

```bash
/home/asus/Github/silent-speech/.venv/bin/python eval/evaluate.py eval/dataset/spk01/manifest.csv \
    --with-correction --debug-roi-dir eval/debug_roi          # dev split only
```
Results go to `eval/results/<timestamp>/` (git-ignored). The first real clip is worth a look: check
`n_frames`, `duration_s` and the ROI contact sheet in `eval/debug_roi/` to confirm the browser's
`.webm` decodes at the expected frame rate.

## Recording tips

Frontal face, even light, camera at mouth height, the same position for every clip. Each clip is 2-6
seconds: start recording, wait a beat, do the sentence, stop. Keep your mouth closed before and after.
Mouth the words as you would in real use; do not exaggerate. Use Retry freely until a take is clean.

## Dry run (no recording, synthetic clips)

```bash
/home/asus/Github/silent-speech/.venv/bin/python eval/recorder/dry_run.py --evaluate
```
Writes only to a temporary directory. Checks the whole save/manifest/evaluate path with a still
photo; the WER it prints is meaningless. Tests: `python -m unittest discover -s eval/tests` (venv python).
