import { useCallback, useEffect, useRef, useState } from "react";
import { connectLive, unlockSound } from "./api.js";
import { getSettings } from "./settings.js";

// Hold to speak, shared by the live and call screens: front camera + one live connection
// (backend/streaming.py). While the button is held, ~25 frames a second go to the Ascent,
// and each group of sure words comes back as soon as it is read, with its voice.
//   onStart()                  a hold began
//   onSay({text, audio, emotion})  a group of words, in order (the server also says it into a call)
//   onDone({text, emotion})    everything was said after the release ("" if nothing was read)
//   onError(message or null)
// holdButton: the props for the hold-to-speak button. Space does the same on a laptop.

const FRAME_MS = 40; // 25 frames a second, like the lip reader was trained on
const JPEG_QUALITY = 0.85; // lower and the lip reader reads clearly worse (measured on our clips)

export function useLiveReader({ onStart, onSay, onDone, onError }) {
  const streamRef = useRef(null);
  const videoEl = useRef(null);
  // A callback ref, so a preview that mounts later (e.g. a new call) still shows the camera
  const videoRef = useCallback((el) => {
    videoEl.current = el;
    if (el && streamRef.current) el.srcObject = streamRef.current;
  }, []);
  const liveRef = useRef(null);
  const holdingRef = useRef(false);
  const waitRef = useRef(null);
  const on = useRef(null); // the latest callbacks, for the connection opened once
  on.current = { onStart, onSay, onDone, onError };
  const [cameraOn, setCameraOn] = useState(false);
  const [connected, setConnected] = useState(false);
  const [holding, setHolding] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [heard, setHeard] = useState(null); // {heard, pending, face} while reading
  const [mood, setMood] = useState(null); // the emotion the voice is using right now

  function finished() {
    clearTimeout(waitRef.current);
    waitRef.current = null;
    setFinishing(false);
  }

  // One live connection while the screen is open
  useEffect(() => {
    const live = connectLive({
      status(open) {
        setConnected(open);
        if (!open && (holdingRef.current || waitRef.current)) {
          holdingRef.current = false;
          setHolding(false);
          finished();
          on.current.onError("Lost the connection to the Ascent. Check the Wi-Fi, then try again.");
        }
      },
      heard: setHeard,
      say(piece) {
        setMood(piece.emotion);
        on.current.onSay(piece);
      },
      done(message) {
        finished();
        setHeard(null);
        on.current.onDone(message);
      },
      error({ message }) {
        finished();
        on.current.onError(message);
      },
    });
    liveRef.current = live;
    return () => live.close();
  }, []);

  // Stop the camera when leaving the screen
  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);

  // Space bar = the button (laptops); switching away from the page releases it
  useEffect(() => {
    const inField = (e) => /INPUT|TEXTAREA/.test(e.target.tagName);
    const down = (e) => {
      if (e.code !== "Space" || inField(e)) return;
      e.preventDefault();
      if (!e.repeat) press();
    };
    const up = (e) => {
      if (e.code !== "Space" || inField(e)) return;
      e.preventDefault();
      release();
    };
    const hidden = () => document.hidden && release();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      document.removeEventListener("visibilitychange", hidden);
    };
  });

  async function startCamera() {
    on.current.onError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 25 } },
      });
      streamRef.current = stream;
      if (videoEl.current) videoEl.current.srcObject = stream;
      setCameraOn(true);
    } catch (err) {
      // navigator.mediaDevices is undefined on plain http (except localhost)
      on.current.onError(`Camera error: ${err.message}. Phones need HTTPS — see the README for tunnels.`);
    }
  }

  // While the button is held: ~25 JPEG frames a second to the Ascent
  function sendFrames() {
    const video = videoEl.current;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    let next = 0;
    let encoding = false;
    const later = (fn) => (video.requestVideoFrameCallback ? video.requestVideoFrameCallback(fn) : setTimeout(fn, 15));
    const grab = () => {
      if (!holdingRef.current) return;
      later(grab);
      const now = performance.now();
      if (now + 5 < next || encoding || !video.videoWidth) return; // too early, or the last one isn't sent yet
      next = Math.max(next + FRAME_MS, now);
      if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
      }
      context.drawImage(video, 0, 0);
      encoding = true;
      canvas.toBlob(
        async (jpeg) => {
          if (jpeg && holdingRef.current) liveRef.current.frame(now, await jpeg.arrayBuffer());
          encoding = false;
        },
        "image/jpeg",
        JPEG_QUALITY,
      );
    };
    grab();
  }

  function press() {
    unlockSound();
    if (!cameraOn) return void startCamera();
    if (holdingRef.current || waitRef.current || !videoEl.current) return;
    if (!liveRef.current?.ready()) {
      return void on.current.onError("Not connected to the Ascent yet. Check the Wi-Fi, then try again.");
    }
    on.current.onError(null);
    on.current.onStart?.();
    setHeard({ heard: "", pending: "", face: true });
    setMood(null);
    holdingRef.current = true;
    setHolding(true);
    liveRef.current.start(getSettings().voice);
    sendFrames();
  }

  function release() {
    unlockSound(); // iPhones count lifting the finger as a tap, not touching down
    if (!holdingRef.current) return;
    holdingRef.current = false;
    setHolding(false);
    setFinishing(true);
    liveRef.current.stop();
    waitRef.current = setTimeout(() => {
      waitRef.current = null;
      setFinishing(false);
      on.current.onError("The Ascent didn't answer. Try again.");
    }, 20_000);
  }

  const holdButton = {
    onPointerDown(e) {
      e.preventDefault();
      e.currentTarget.setPointerCapture?.(e.pointerId); // lifting the finger anywhere releases
      press();
    },
    onPointerUp: release,
    onPointerCancel: release,
    onLostPointerCapture: release,
    onContextMenu: (e) => e.preventDefault(),
  };

  return { videoRef, cameraOn, connected, holding, finishing, heard, mood, startCamera, holdButton };
}
