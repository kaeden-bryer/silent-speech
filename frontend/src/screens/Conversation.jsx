import { useEffect, useRef, useState } from "react";
import { api, play, unlockSound } from "../api.js";
import { getSettings, useSettings } from "../settings.js";
import { useClipRecorder } from "../useClipRecorder.js";
import { Avatar, Icon, Logo, paths } from "../components/ui.jsx";

// The phone-call channel: dial a real number (Twilio, backend/phone.py), then
// every mouthed or typed sentence is spoken into the call. What the other person
// says comes back as captions in GET /api/history, polled while the call is on.

const QUICK_PHRASES = ["Yes", "No", "Can you repeat that?", "One moment please"];
const POLL_MS = 700;

// Cycle pastel tones through the quick-phrase chips, like the reference design
const CHIP_TONES = [
  "bg-blush text-blush-deep dark:bg-blush-deep/25 dark:text-blush",
  "bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky",
  "bg-peach text-peach-deep dark:bg-peach-deep/25 dark:text-peach",
  "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint",
];

// "(555) 123-4567" -> "+15551234567"; 10 bare digits are taken as a US number
function toE164(raw) {
  const digits = raw.replace(/[^\d+]/g, "");
  const number = /^\d{10}$/.test(digits) ? `+1${digits}` : digits;
  return /^\+[1-9]\d{7,14}$/.test(number) ? number : null;
}

const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export default function Conversation({ onNavigate }) {
  const [settings, update] = useSettings();
  const [active, setActive] = useState(false);
  const [dialing, setDialing] = useState(false);
  const [history, setHistory] = useState([]);
  const [fromTurn, setFromTurn] = useState(0); // history is shared with the live screen: show this call only
  const [startedAt, setStartedAt] = useState(null);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [typed, setTyped] = useState("");
  const endRef = useRef(null);

  const { videoRef, cameraOn, recording, toggle } = useClipRecorder({
    onClip: (clip) => send(api.sendVideo(clip)),
    onError: setError,
  });

  async function refresh() {
    try {
      const h = await api.history();
      setHistory(h.history);
      setActive((was) => {
        if (was && !h.call_active) setNotice("Call ended");
        return h.call_active;
      });
    } catch {
      // the next poll tries again
    }
  }

  // Pick up a call already in progress (e.g. after a reload), then poll while it's on
  useEffect(() => void refresh(), []);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const start = startedAt ?? Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [active, startedAt]);

  useEffect(() => endRef.current?.scrollIntoView({ block: "end" }), [history.length]);

  async function dial(event) {
    event.preventDefault();
    unlockSound();
    const number = toE164(settings.callNumber);
    if (!number) return void setError("Enter a full phone number, e.g. +1 555 123 4567.");
    setError(null);
    setNotice(null);
    setDialing(true);
    try {
      await api.call(number);
      setFromTurn(history.length);
      setStartedAt(Date.now());
      setSeconds(0);
      setActive(true);
    } catch (err) {
      // 503 = calls not set up, or Twilio unreachable (no internet)
      setError(`Couldn't call: ${err.message.replace(/^\d+: /, "")}`);
    } finally {
      setDialing(false);
    }
  }

  async function hangUp() {
    await api.hangup().catch(() => {});
    setActive(false);
    setStartedAt(null);
    setNotice("Call ended");
  }

  async function send(request) {
    setBusy(true);
    setError(null);
    try {
      const r = await request;
      if (!r.text) setError("Didn't catch that — mouth one short sentence, or type it.");
      else if (getSettings().hearMyself) play(r);
      refresh();
    } catch (err) {
      setError(`Backend error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  function sendText(text) {
    if (!text.trim()) return;
    unlockSound();
    send(api.sendText(text.trim()));
  }

  const turns = history.slice(fromTurn).filter((t) => t.speaker === "me" || settings.captions);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-24 pt-5 md:max-w-[1024px]">
      <header className="mb-4 flex items-center gap-3 md:mb-7">
        <button
          title="Back to live"
          aria-label="Back to live"
          onClick={() => onNavigate("live")}
          className="grid size-10 shrink-0 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
        >
          <Icon d={paths.back} className="size-5.5" />
        </button>
        <Logo className="size-[40px]" />
        <div className="min-w-0 flex-1 text-base font-extrabold md:text-2xl md:tracking-tight">Phone call</div>
        <span
          role="status"
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${
            active
              ? "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint"
              : "bg-muted/15 text-muted"
          }`}
        >
          <span className={`size-1.5 rounded-full ${active ? "animate-pulse bg-mint-deep" : "bg-muted"}`} />
          {active ? `ON CALL · ${clock(seconds)}` : dialing ? "DIALING…" : "NOT IN A CALL"}
        </span>
      </header>

      {!active ? (
        <form onSubmit={dial} className="rounded-2xl border border-line bg-card p-5 dark:border-line-dark dark:bg-panel">
          <label htmlFor="number" className="text-[11px] font-bold tracking-widest text-muted uppercase">
            Who are you calling?
          </label>
          <input
            id="number"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={settings.callNumber}
            onChange={(e) => update({ callNumber: e.target.value })}
            placeholder="+1 555 123 4567"
            className="mt-2 w-full rounded-xl border border-line bg-transparent px-3.5 py-3 text-lg font-semibold outline-none placeholder:text-muted focus:border-accent dark:border-line-dark"
          />
          <button
            disabled={dialing}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-accent py-3 text-base font-bold text-white shadow-accent transition hover:bg-accent-strong disabled:opacity-50"
          >
            <Icon d={paths.phone} className="size-5" />
            {dialing ? "Dialing…" : "Call"}
          </button>
          <p className="mt-3 text-xs text-muted">
            Your mouthed sentences are spoken into the call, and what they say shows up here as captions.
            Calls need the internet; everything else works without it.
          </p>
          {(error || notice) && (
            <p role="alert" className={`mt-3 text-center text-sm font-semibold ${error ? "text-red-500" : "text-muted"}`}>
              {error ?? notice}
            </p>
          )}
        </form>
      ) : (
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:gap-6">
          {/* Camera + record: the same tap-to-start / tap-to-stop as the live screen */}
          <div className="flex flex-col gap-3 md:w-[360px] md:shrink-0">
            <div className="relative aspect-[4/3] w-full overflow-hidden rounded-3xl bg-camera shadow-xl shadow-black/20">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className={`absolute inset-0 size-full -scale-x-100 object-cover ${cameraOn ? "" : "hidden"}`}
              />
              <div className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-bold text-white backdrop-blur">
                {recording ? "Reading your lips…" : busy ? "Saying it…" : cameraOn ? "Camera on ✓" : "Camera off"}
              </div>
            </div>
            <div className="flex items-center justify-center gap-[24px]">
              <button
                title={recording ? "Stop and say it" : cameraOn ? "Start reading" : "Start camera"}
                aria-label={recording ? "Stop and say it" : cameraOn ? "Start reading" : "Start camera"}
                onClick={() => {
                  unlockSound();
                  toggle();
                }}
                disabled={busy}
                className={`grid size-[72px] place-items-center rounded-full text-white ring-4 transition disabled:opacity-50 ${
                  recording
                    ? "bg-red-500 shadow-xl shadow-red-500/40 ring-red-500/20 hover:bg-red-600"
                    : "bg-accent shadow-accent ring-accent/20 hover:bg-accent-strong"
                }`}
              >
                {recording ? (
                  <span className="size-6 rounded-md bg-white" />
                ) : (
                  <Icon d={cameraOn ? paths.speaker : paths.camera} className="size-7" />
                )}
              </button>
              <button
                title="Hang up"
                aria-label="Hang up"
                onClick={hangUp}
                className="grid size-[56px] place-items-center rounded-full bg-red-500 text-white shadow-md shadow-red-500/30 transition hover:bg-red-600"
              >
                <Icon d={paths.phone} className="size-6 rotate-[135deg]" />
              </button>
            </div>
          </div>

          {/* Transcript, quick phrases, typing */}
          <div className="flex min-w-0 flex-1 flex-col gap-3 rounded-2xl border border-line bg-card p-4 dark:border-line-dark dark:bg-panel">
            <div className="max-h-[40vh] min-h-32 space-y-4 overflow-y-auto md:max-h-[50vh]">
              {turns.length === 0 && (
                <p className="py-6 text-center text-sm text-muted">
                  Ringing… once they answer, mouth a sentence or tap a phrase.
                </p>
              )}
              {turns.map((t, i) => (
                <div key={i} className="flex gap-3">
                  <Avatar name={t.speaker === "me" ? "You" : "Them"} tone={t.speaker === "me" ? 0 : 1} />
                  <div className="min-w-0">
                    <div className={`text-sm font-bold ${t.speaker === "me" ? "text-accent-strong dark:text-accent-tint" : ""}`}>
                      {t.speaker === "me" ? "You" : "Them"}
                    </div>
                    <p className="mt-0.5 break-words text-base leading-relaxed text-body/90 dark:text-white/85">{t.text}</p>
                  </div>
                </div>
              ))}
              <div ref={endRef} />
            </div>

            {error && (
              <p role="alert" className="text-center text-xs font-semibold text-red-500">
                {error}
              </p>
            )}

            {/* Quick phrases: one tap beats mouthing for the predictable turns */}
            <div className="flex gap-2 overflow-x-auto [scrollbar-width:none]">
              {QUICK_PHRASES.map((p, i) => (
                <button
                  key={p}
                  disabled={busy}
                  onClick={() => sendText(p)}
                  className={`shrink-0 rounded-full px-3.5 py-2 text-sm font-semibold transition hover:brightness-95 disabled:opacity-50 ${CHIP_TONES[i % CHIP_TONES.length]}`}
                >
                  {p}
                </button>
              ))}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                sendText(typed);
                setTyped("");
              }}
              className="flex gap-2"
            >
              <input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder="…or type a sentence"
                className="min-w-0 flex-1 rounded-xl border border-line bg-transparent px-3 text-base outline-none placeholder:text-muted focus:border-accent dark:border-line-dark"
              />
              <button
                disabled={busy}
                aria-label="Say it"
                className="rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white transition hover:bg-accent-strong disabled:opacity-50"
              >
                <Icon d={paths.send} className="size-5" />
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
