# Offline Demo Instructions

How to run Silent Speech with **no internet**. The Ascent (the big computer) makes its own Wi-Fi network. Your iPhone joins it and talks to the Ascent directly.

You need: the Ascent, an iPhone, and this project folder on the Ascent.

## How it works

- The **iPhone** films your lips and plays the voice.
- The **Ascent** reads the lips and makes the voice.
- The iPhone's camera only works on a **secure** (`https://`) page. Normally that needs the internet, so we make our own secure certificate and teach the iPhone to trust it. You do this once.

---

## Part 1: One-time setup (do this before the demo, while you still have internet)

All commands are typed into a terminal **on the Ascent**.

### 1. Open the project folder
```bash
cd ~/Github/silent-speech
```

### 2. Start the Ascent's Wi-Fi network
```bash
sudo scripts/setup_network.sh hotspot
```
It prints the network name and password (by default `SilentSpeech` / `silentspeech`).

> This uses the Ascent's Wi-Fi card. The Ascent's Ethernet cable keeps working as normal.
> The network runs on **5 GHz** (channel 149) because the 2.4 GHz band is jammed at a busy venue. The iPhone must support 5 GHz (all recent ones do). If the Ascent can't host a 5 GHz network, the script prints a message and falls back to 2.4 GHz.

### 3. Make the security certificate
```bash
scripts/setup_network.sh certs
```
You should see a line starting `Server cert covers:`. If it says an error, stop and ask for help.

### 4. Join the network on the iPhone
Settings → Wi-Fi → pick **SilentSpeech** → enter the password. The iPhone will say "No Internet Connection". That is fine.

### 5. Install the certificate on the iPhone
1. On the Ascent, run:
   ```bash
   scripts/setup_network.sh serve-ca
   ```
   It prints a web address like `http://10.42.0.1:8080/ca.crt`.
2. On the iPhone, open **Safari** and type that address. Tap **Allow** when it asks to download a profile.
3. iPhone: **Settings → Profile Downloaded → Install** (enter your passcode, tap Install again).
4. iPhone: **Settings → General → About → Certificate Trust Settings** → switch on **Silent Speech Local CA** → Continue.
5. On the Ascent, press **Ctrl+C** to stop `serve-ca`.

You never have to do Part 1, step 5 again, unless you delete the profile from the iPhone.

---

## Part 2: Running the demo (every time)

### 1. Make sure the hotspot is on
```bash
cd ~/Github/silent-speech
sudo scripts/setup_network.sh hotspot
```
Then check the iPhone is joined to **SilentSpeech**.

### 2. Start the app on the Ascent
```bash
cd ~/Github/silent-speech/backend
source ../.venv/bin/activate
python server.py
```
Wait until you see `Uvicorn running on https://0.0.0.0:8000`. The first start takes a minute or two while the models load. (`Serving HTTPS on port 8000` appears near the start, before the models load, so it does not mean the app is ready yet.)

> If it says `serving plain HTTP`, the `certs/` folder is missing. Run `scripts/setup_network.sh certs` (Part 1, step 3) and start again. The iPhone camera will not work over plain HTTP.

> The warnings about `dropout`, `weight_norm`, `torch.jit` and the Hugging Face Hub are harmless.

> If you see `address already in use`, another copy of the app is running. Stop it first (go to its terminal and press **Ctrl+C**), then try again.

### 3. Open the page on the iPhone
In Safari, go to:

**https://10.42.0.1:8000**

- Tap **Allow** when Safari asks for camera access.
- Hold the phone so your face is in the picture, in good, even light.

### 4. Use it
1. Tap once to **start recording**.
2. Silently mouth a short sentence (3–8 words work best). Look at the camera.
3. Tap again to **stop**.
4. After a moment the phone speaks the sentence out loud.

Phrases from `backend/demo_phrases.txt` work most reliably.

---

## When you're done
- Press **Ctrl+C** in the terminal running `python server.py`.
- Turn off the hotspot:
  ```bash
  sudo scripts/setup_network.sh hotspot-down
  ```

---

## Something went wrong?

| What you see | What to do |
|---|---|
| Safari says "This connection is not private" | The certificate isn't trusted yet. Redo Part 1, step 5. Make sure **Silent Speech Local CA** is switched on in Certificate Trust Settings. |
| iPhone says "Unable to join the network" | Move the phone close to the Ascent. Forget **SilentSpeech** on the iPhone and join again. Turn off **Private Wi-Fi Address** for that network (tap the (i) next to it) and turn off any VPN. Check the script did not print the 2.4 GHz fallback message. At a crowded venue 2.4 GHz often fails. |
| `python server.py` prints a lot and then returns to the prompt | You are running an old copy of `server.py`. Pull the latest code (it needs the block at the bottom that starts the web server). |
| The page won't load at all | Check the iPhone is joined to **SilentSpeech** (not another Wi-Fi) and that `python server.py` is still running. |
| Camera doesn't turn on | You must use the `https://` address, not `http://`. Check Settings → Safari → Camera is set to Ask or Allow. |
| Wrong words come out | Lip reading is hard. Use short phrases from `backend/demo_phrases.txt`, face the camera, and use good lighting. |
| The Ascent's address changed (for example you joined it to a different network) | Run `scripts/setup_network.sh certs` again, restart `python server.py`, and use the new address. |
| First attempt is slow | Normal. Do one practice run before showing anyone. |

## Before a real demo: checklist
- [ ] Did the full run once, with the Ascent's Ethernet cable **unplugged** and your venue's Wi-Fi off.
- [ ] CA installed and trusted on the iPhone.
- [ ] Phone charged; Ascent plugged in.
- [ ] Wrote the three commands from Part 2 on a sticky note.
