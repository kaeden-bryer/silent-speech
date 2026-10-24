import { useEffect, useRef, useState } from "react";
import { api, play, unlockSound } from "../api.js";
import { getSettings, useSettings } from "../settings.js";
import { EmotionChip, Icon, Logo, paths } from "../components/ui.jsx";

// The app's home screen, wired to the backend: mouth a sentence on camera
// (or type one), the pipeline corrects it, and it's spoken aloud.
// The backend returns one corrected text + the raw lip-reading, so the
// "Did you say…" card offers those two readings (top-3 when the model has it).

const CHANNELS = [
  { label: "Speaker", icon: paths.speaker, active: true },
  { label: "Phone call", icon: paths.phone },
  { label: "Meeting", icon: paths.camera },
];

export default function LiveCapture({ onNavigate }) {
  const [settings] = useSettings();
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");

  // Stop the camera when leaving the screen
  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);

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

  function toggleRecord() {
    unlockSound();
    if (!cameraOn) return void startCamera();
    if (recording) return void recorderRef.current?.stop();
    const chunks = [];
    const rec = new MediaRecorder(streamRef.current);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = () => {
      setRecording(false);
      send(api.sendVideo(new Blob(chunks, { type: rec.mimeType })));
    };
    recorderRef.current = rec;
    rec.start();
    setResult(null);
    setRecording(true);
  }

  async function send(request) {
    setBusy(true);
    setError(null);
    try {
      const r = await request;
      setResult(r);
      const s = getSettings();
      if (!r.text) {
        setError("Didn't catch that — mouth one short sentence, or type it.");
      } else if (s.autoSpeak && !(s.confirmNumbers && /\d/.test(r.text))) {
        play(r);
      }
    } catch (err) {
      setError(`Backend error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  function submitTyped(event) {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    unlockSound();
    setTyped("");
    setTyping(false);
    send(api.sendText(text));
  }

  const candidates = result?.text
    ? [
        { text: result.text, note: "best match", picked: true },
        ...(result.raw_text && result.raw_text !== result.text
          ? [{ text: result.raw_text, note: "as read" }]
          : []),
      ]
    : [];

  const status = recording
    ? { label: "READING", tone: "bg-red-500/10 text-red-500", dot: "bg-red-500 animate-pulse" }
    : busy
      ? { label: "THINKING", tone: "bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter", dot: "bg-butter-deep animate-pulse" }
      : { label: cameraOn ? "READY" : "CAMERA OFF", tone: "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint", dot: "bg-mint-deep" };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-24 pt-5 md:max-w-5xl">
      <header className="mb-4 flex items-center gap-3">
        <Logo className="size-10" />
        <div className="min-w-0 flex-1">
          <div className="text-base font-extrabold">Silent Speech</div>
          <div className="truncate text-sm text-muted">Speaker mode — speaks out loud on this device</div>
        </div>
        <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${status.tone}`}>
          <span className={`size-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        <button
          title="Settings"
          onClick={() => onNavigate("settings")}
          className="grid size-10 shrink-0 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
        >
          <Icon d={paths.settings} className="size-5.5" />
        </button>
      </header>

      {/* Output channel: where the voice goes */}
      <div className="mb-4 flex gap-2 overflow-x-auto [scrollbar-width:none]">
        {CHANNELS.map((c) => (
          <button
            key={c.label}
            className={`flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition ${
              c.active
                ? "bg-accent text-white shadow-md shadow-accent/30"
                : "border border-line bg-card text-muted hover:text-body dark:border-line-dark dark:bg-panel dark:hover:text-white"
            }`}
          >
            <Icon d={c.icon} className="size-4.5" />
            {c.label}
          </button>
        ))}
      </div>

      {/* Side by side on desktop, stacked on phones */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start">
        {/* Camera preview */}
        <div className="relative aspect-[3/4] max-h-[48vh] w-full overflow-hidden rounded-3xl bg-panel shadow-xl shadow-black/20 md:max-h-none md:flex-1 dark:bg-panel-2">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className={`absolute inset-0 size-full -scale-x-100 object-cover ${cameraOn ? "" : "hidden"}`}
          />

          {!cameraOn && (
            <div className="absolute inset-0 grid place-items-center">
              <div className="flex flex-col items-center gap-4">
                <svg viewBox="0 0 200 260" className="w-40 text-muted/40" fill="none" stroke="currentColor" strokeWidth="3">
                  <ellipse cx="100" cy="100" rx="55" ry="70" />
                  <path d="M80 125 q20 14 40 0" strokeLinecap="round" />
                  <circle cx="82" cy="88" r="4" fill="currentColor" stroke="none" />
                  <circle cx="118" cy="88" r="4" fill="currentColor" stroke="none" />
                </svg>
                <button
                  onClick={startCamera}
                  className="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-accent/40 transition hover:bg-accent-strong"
                >
                  <Icon d={paths.camera} className="size-5" />
                  Start camera
                </button>
              </div>
            </div>
          )}

          {cameraOn && (
            <div className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-bold text-white backdrop-blur">
              {recording ? "Reading your lips…" : "Camera on ✓"}
            </div>
          )}

          {(busy || result?.raw_text) && (
            <div className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/55 px-4 py-2.5 backdrop-blur">
              <div className="text-[10px] font-bold tracking-widest text-white/50 uppercase">
                {busy ? "Reading…" : "Heard"}
              </div>
              <div className="text-sm font-semibold text-white">
                {busy ? "…" : result?.raw_text || "—"}
              </div>
            </div>
          )}
        </div>

        {/* Result + confirm */}
        <div className="flex flex-col gap-3 md:w-[26rem] md:shrink-0">
          <div className="rounded-2xl border border-line bg-card p-4 dark:border-line-dark dark:bg-panel">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold tracking-widest text-muted uppercase">
                Did you say…
              </span>
              <span className="flex items-center gap-1.5">
                {result?.emotion && result.emotion !== "neutral" && <EmotionChip emotion={result.emotion} />}
                {result?.text && settings.confirmNumbers && /\d/.test(result.text) && (
                  <span className="rounded-full bg-butter px-2 py-0.5 text-[11px] font-bold text-butter-deep dark:bg-butter-deep/25 dark:text-butter">
                    has a number — tap to speak
                  </span>
                )}
              </span>
            </div>

            {candidates.length > 0 ? (
              <div className="space-y-2">
                {candidates.map((c) => (
                  <button
                    key={c.text}
                    onClick={() => play({ ...result, text: c.text, audio: c.picked ? result.audio : null })}
                    className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3.5 py-3 text-left text-base font-semibold transition ${
                      c.picked
                        ? "border-accent bg-accent-soft text-accent-strong dark:bg-accent/15 dark:text-accent-tint"
                        : "border-line text-body/80 hover:border-accent/50 dark:border-line-dark dark:text-white/80"
                    }`}
                  >
                    <span className="min-w-0 break-words">{c.text}</span>
                    <span className={`shrink-0 text-xs ${c.picked ? "" : "text-muted"}`}>{c.note}</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-line px-3.5 py-6 text-center text-sm text-muted dark:border-line-dark">
                {error ?? (busy ? "Reading your sentence…" : "Mouth a sentence on camera, or type one below.")}
              </p>
            )}
            {error && candidates.length > 0 && (
              <p className="mt-2 text-center text-xs font-semibold text-red-500">{error}</p>
            )}

            <button
              disabled={!result?.text}
              onClick={() => {
                unlockSound();
                play(result);
              }}
              className="mt-3 w-full rounded-xl bg-accent py-3 text-base font-bold text-white shadow-md shadow-accent/30 transition hover:bg-accent-strong disabled:opacity-40 disabled:shadow-none"
            >
              {result?.text ? `Speak it — "${result.text}"` : "Speak it"}
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
                {candidates.length > 0 ? "None of these — type it" : "Type instead"}
              </button>
            )}
          </div>

          {/* Record controls */}
          <div className="flex items-center justify-center gap-8 py-2">
            <button
              title="Keyboard fallback"
              onClick={() => setTyping((t) => !t)}
              className="grid size-14 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.keyboard} />
            </button>
            <button
              title={recording ? "Stop and speak" : cameraOn ? "Start reading" : "Start camera"}
              onClick={toggleRecord}
              disabled={busy}
              className={`grid size-18 place-items-center rounded-full text-white shadow-xl ring-4 transition disabled:opacity-50 ${
                recording
                  ? "bg-red-500 shadow-red-500/40 ring-red-500/20 hover:bg-red-600"
                  : "bg-accent shadow-accent/40 ring-accent/20 hover:bg-accent-strong"
              }`}
            >
              {recording ? (
                <span className="size-6 rounded-md bg-white" />
              ) : (
                <Icon d={paths.camera} className="size-7" />
              )}
            </button>
            <button
              title="Replay last sentence"
              disabled={!result?.text}
              onClick={() => {
                unlockSound();
                play(result);
              }}
              className="grid size-14 place-items-center rounded-full border border-line text-muted transition hover:text-body disabled:opacity-40 dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.speaker} />
            </button>
          </div>
          <p className="-mt-2 text-center text-xs text-muted">
            {recording ? "Mouth one sentence, then tap to stop" : cameraOn ? "Tap to start reading" : "Tap to turn on the camera"}
          </p>
        </div>
      </div>
    </div>
  );
}
