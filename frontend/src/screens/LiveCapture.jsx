import { useEffect, useRef, useState } from "react";
import { api, connectLive, playInOrder, unlockSound } from "../api.js";
import { getSettings, useSettings } from "../settings.js";
import { EmotionChip, Icon, Logo, paths } from "../components/ui.jsx";

// The app's home screen, wired to the backend: hold the button and mouth a sentence.
// The lips are read live on the Ascent (backend/streaming.py) and each group of words is
// spoken as soon as it is sure, while you are still mouthing. Release to stop.
// Typing a sentence works too.

const CHANNELS = [
  { label: "Speaker", icon: paths.speaker, active: true },
  { label: "Phone call", icon: paths.phone, screen: "call" },
];
const FRAME_MS = 40; // 25 frames a second, like the lip reader was trained on
const JPEG_QUALITY = 0.85; // lower and the lip reader reads clearly worse (measured on our clips)

// Speak right away, unless the settings say to wait for a tap
function speaksByItself(text) {
  const s = getSettings();
  return s.autoSpeak && !(s.confirmNumbers && /\d/.test(text));
}

export default function LiveCapture({ onNavigate }) {
  const [settings] = useSettings();
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const liveRef = useRef(null);
  const holdingRef = useRef(false);
  const piecesRef = useRef([]); // what the server voiced during this hold
  const heldBackRef = useRef(false); // a piece waited for a tap instead of playing
  const waitRef = useRef(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [connected, setConnected] = useState(false);
  const [holding, setHolding] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [heard, setHeard] = useState(null); // {heard, pending, face} while reading
  const [result, setResult] = useState(null); // {text, emotion, pieces, spoken} once said
  const [error, setError] = useState(null);
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [speaking, setSpeaking] = useState(0); // pieces playing or waiting to

  function voice(piece) {
    setSpeaking((n) => n + 1);
    playInOrder(piece, { onEnd: () => setSpeaking((n) => n - 1) });
  }

  function finished() {
    clearTimeout(waitRef.current);
    waitRef.current = null;
    setFinishing(false);
  }

  // One live connection while this screen is open
  useEffect(() => {
    const live = connectLive({
      status(open) {
        setConnected(open);
        if (!open && (holdingRef.current || waitRef.current)) {
          holdingRef.current = false;
          setHolding(false);
          finished();
          setError("Lost the connection to the Ascent. Check the Wi-Fi, then try again.");
        }
      },
      heard: setHeard,
      say(piece) {
        piecesRef.current.push(piece);
        if (speaksByItself(piece.text)) voice(piece);
        else heldBackRef.current = true;
      },
      done({ text, emotion }) {
        finished();
        setHeard(null);
        setResult({ text, emotion, pieces: piecesRef.current, spoken: !heldBackRef.current });
        if (!text) setError("Didn't catch that. Hold the button while you mouth, with your face in view.");
      },
      error({ message }) {
        finished();
        setError(message);
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
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 25 } },
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setCameraOn(true);
    } catch (err) {
      // navigator.mediaDevices is undefined on plain http (except localhost)
      setError(`Camera error: ${err.message}. Phones need HTTPS — see the README for tunnels.`);
    }
  }

  // While the button is held: ~25 JPEG frames a second to the Ascent
  function sendFrames() {
    const video = videoRef.current;
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
    if (holdingRef.current || waitRef.current) return;
    if (!liveRef.current?.ready()) {
      return void setError("Not connected to the Ascent yet. Check the Wi-Fi, then try again.");
    }
    setError(null);
    setResult(null);
    setTyping(false);
    setHeard({ heard: "", pending: "", face: true });
    piecesRef.current = [];
    heldBackRef.current = false;
    holdingRef.current = true;
    setHolding(true);
    liveRef.current.start();
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
      setError("The Ascent didn't answer. Try again.");
    }, 20_000);
  }

  async function submitTyped(event) {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    unlockSound();
    setTyped("");
    setTyping(false);
    setError(null);
    setFinishing(true);
    try {
      const r = await api.sendText(text);
      const piece = { text: r.text, audio: r.audio };
      const spoken = Boolean(r.text) && speaksByItself(r.text);
      setResult({ text: r.text, emotion: r.emotion, pieces: [piece], spoken });
      if (spoken) voice(piece);
    } catch (err) {
      setError(`Backend error: ${err.message}`);
    } finally {
      setFinishing(false);
    }
  }

  function sayAgain() {
    unlockSound();
    result?.pieces.forEach(voice);
  }

  const live = holding || (finishing && heard);
  const status = holding
    ? { label: "READING", tone: "bg-red-500/10 text-red-500", dot: "bg-red-500 animate-pulse" }
    : finishing
      ? { label: "THINKING", tone: "bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter", dot: "bg-butter-deep animate-pulse" }
      : speaking > 0
        ? { label: "SPEAKING", tone: "bg-accent-soft text-accent-strong dark:bg-accent/15 dark:text-accent-tint", dot: "bg-accent animate-pulse" }
        : cameraOn && !connected
          ? { label: "CONNECTING", tone: "bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter", dot: "bg-butter-deep animate-pulse" }
          : { label: cameraOn ? "READY" : "CAMERA OFF", tone: "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint", dot: "bg-mint-deep" };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-24 pt-5 md:max-w-[1024px]">
      <header className="mb-4 flex items-center gap-3 md:mb-7">
        <Logo className="size-[40px]" />
        <div className="min-w-0 flex-1">
          <div className="text-base font-extrabold md:text-2xl md:tracking-tight">Silent Speech</div>
        </div>
        <span
          role="status"
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${status.tone}`}
        >
          <span className={`size-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        <button
          title="Settings"
          aria-label="Settings"
          onClick={() => onNavigate("settings")}
          className="grid size-10 shrink-0 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
        >
          <Icon d={paths.settings} className="size-5.5" />
        </button>
      </header>

      {/* Output channel: where the voice goes */}
      <div className="mb-4 flex gap-2 overflow-x-auto [scrollbar-width:none] md:mb-7">
        {CHANNELS.map((c) => (
          <button
            key={c.label}
            onClick={() => c.screen && onNavigate(c.screen)}
            className={`flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition ${
              c.active
                ? "bg-accent text-white shadow-accent"
                : "border border-line bg-card text-muted hover:text-body dark:border-line-dark dark:bg-panel dark:hover:text-white"
            }`}
          >
            <Icon d={c.icon} className="size-4.5" />
            {c.label}
          </button>
        ))}
      </div>

      {/* Side by side on desktop, stacked on phones */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:gap-6">
        {/* Camera preview: stays navy until a real stream is granted */}
        <div className="relative aspect-[3/4] max-h-[48vh] w-full overflow-hidden rounded-3xl bg-camera shadow-xl shadow-black/20 md:max-h-none md:flex-1">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className={`absolute inset-0 size-full -scale-x-100 object-cover ${cameraOn ? "" : "hidden"}`}
          />

          {!cameraOn && (
            <div className="absolute inset-0 grid place-items-center">
              <button
                onClick={() => {
                  unlockSound();
                  startCamera();
                }}
                className="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong"
              >
                <Icon d={paths.camera} className="size-5" />
                Start camera
              </button>
            </div>
          )}

          {cameraOn && (
            <div className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-bold text-white backdrop-blur">
              {holding ? "Reading your lips… release to stop" : connected ? "Hold the button to speak" : "Connecting to the Ascent…"}
            </div>
          )}

          {(live || result?.text) && (
            <div className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/55 px-4 py-2.5 backdrop-blur">
              <div className="text-[10px] font-bold tracking-widest text-white/50 uppercase">
                {live ? "Reading…" : "Said"}
              </div>
              <div className="text-sm font-semibold text-white">
                {live ? (
                  <>
                    {heard?.heard} <span className="text-white/50">{heard?.pending}</span>
                    {!heard?.heard && !heard?.pending && "…"}
                  </>
                ) : (
                  result.text
                )}
              </div>
            </div>
          )}
        </div>

        {/* Result + confirm */}
        <div className="flex flex-col gap-3 md:w-[420px] md:shrink-0">
          <div className="rounded-2xl border border-line bg-card p-4 dark:border-line-dark dark:bg-panel">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold tracking-widest text-muted uppercase">
                {live ? "Reading…" : result?.spoken ? "What you said" : "Did you say…"}
              </span>
              <span className="flex items-center gap-1.5">
                {!live && result?.emotion && result.emotion !== "neutral" && <EmotionChip emotion={result.emotion} />}
                {!live && result?.text && !result.spoken && settings.confirmNumbers && /\d/.test(result.text) && (
                  <span className="rounded-full bg-butter px-2 py-0.5 text-[11px] font-bold text-butter-deep dark:bg-butter-deep/25 dark:text-butter">
                    has a number — tap to speak
                  </span>
                )}
              </span>
            </div>

            {live ? (
              <div aria-live="polite" className="rounded-xl border-2 border-accent bg-accent-soft px-3.5 py-3 text-base font-semibold text-accent-strong dark:bg-accent/15 dark:text-accent-tint">
                {heard?.heard} <span className="opacity-50">{heard?.pending}</span>
                {!heard?.heard && !heard?.pending && (holding ? "Mouth your sentence…" : "Finishing…")}
                {heard && !heard.face && (
                  <p role="alert" className="mt-1 text-xs font-semibold text-red-500">
                    Can't see your face — hold the phone in front of you.
                  </p>
                )}
              </div>
            ) : result?.text ? (
              <button
                aria-pressed="true"
                onClick={sayAgain}
                className="flex w-full items-center justify-between gap-3 rounded-xl border-2 border-accent bg-accent-soft px-3.5 py-3 text-left text-base font-semibold text-accent-strong transition dark:bg-accent/15 dark:text-accent-tint"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Icon d={paths.check} className="size-4.5 shrink-0" />
                  <span className="min-w-0 break-words">{result.text}</span>
                </span>
                <span className="shrink-0 text-xs">{result.spoken ? "spoken ✓" : "tap to speak"}</span>
              </button>
            ) : (
              <p className="rounded-xl border border-dashed border-line px-3.5 py-6 text-center text-sm text-muted dark:border-line-dark">
                {error ?? (finishing ? "Reading your sentence…" : "Hold the button and mouth a sentence, or type one below.")}
              </p>
            )}
            {error && (live || result?.text) && (
              <p role="alert" className="mt-2 text-center text-xs font-semibold text-red-500">
                {error}
              </p>
            )}

            <button
              disabled={!result?.text || live}
              onClick={sayAgain}
              className="mt-3 w-full rounded-xl bg-accent py-3 text-base font-bold text-white shadow-accent transition hover:bg-accent-strong disabled:opacity-40 disabled:shadow-none"
            >
              {result?.spoken ? "Say it again" : result?.text ? `Speak it — "${result.text}"` : "Speak it"}
            </button>

            {typing ? (
              <form onSubmit={submitTyped} className="mt-2 flex gap-2">
                <input
                  autoFocus
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="Type a sentence…"
                  className="min-w-0 flex-1 rounded-xl border border-line bg-transparent px-3 text-base outline-none placeholder:text-muted focus:border-accent dark:border-line-dark"
                />
                <button className="rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white transition hover:bg-accent-strong">
                  <Icon d={paths.send} className="size-5" />
                </button>
              </form>
            ) : (
              <button
                onClick={() => setTyping(true)}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-line py-2.5 text-sm font-bold text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
              >
                <Icon d={paths.keyboard} className="size-5" />
                {result?.text ? "Not right — type it" : "Type instead"}
              </button>
            )}
          </div>

          {/* Hold-to-speak controls: first on phones so they never need a scroll */}
          <div className="order-first flex items-center justify-center gap-[24px] py-2 md:order-none">
            <button
              title="Keyboard fallback"
              aria-label="Keyboard fallback"
              onClick={() => setTyping((t) => !t)}
              className="grid size-[56px] place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.keyboard} />
            </button>
            <button
              title={holding ? "Release to stop" : cameraOn ? "Hold to speak" : "Start camera"}
              aria-label={holding ? "Release to stop" : cameraOn ? "Hold to speak" : "Start camera"}
              aria-pressed={holding}
              disabled={finishing && !holding}
              onPointerDown={(e) => {
                e.preventDefault();
                e.currentTarget.setPointerCapture?.(e.pointerId); // lifting the finger anywhere releases
                press();
              }}
              onPointerUp={release}
              onPointerCancel={release}
              onLostPointerCapture={release}
              onContextMenu={(e) => e.preventDefault()}
              className={`grid size-[72px] touch-none select-none place-items-center rounded-full text-white ring-4 transition [-webkit-touch-callout:none] disabled:opacity-50 ${
                holding
                  ? "scale-110 bg-red-500 shadow-xl shadow-red-500/40 ring-red-500/30"
                  : "bg-accent shadow-accent ring-accent/20 hover:bg-accent-strong"
              }`}
            >
              {holding ? (
                <span className="size-6 animate-pulse rounded-md bg-white" />
              ) : (
                <Icon d={cameraOn ? paths.speaker : paths.camera} className="size-7" />
              )}
            </button>
            <button
              title="Replay last sentence"
              aria-label="Replay last sentence"
              disabled={!result?.text || live}
              onClick={sayAgain}
              className="grid size-[56px] place-items-center rounded-full border border-line text-muted transition hover:text-body disabled:opacity-40 dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.speaker} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
