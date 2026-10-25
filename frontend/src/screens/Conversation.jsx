import { useEffect, useRef, useState } from "react";
import { api, hearCall, play, playInOrder, unlockSound } from "../api.js";
import { getSettings, useSettings } from "../settings.js";
import { useLiveReader } from "../useLiveReader.js";
import { Avatar, CameraChip, HoldButton, Icon, SideButton, paths } from "../components/ui.jsx";

// The phone-call channel: dial a real number (Twilio, backend/phone.py), then hold the
// button and mouth: the lips are read live and each group of words is spoken into the call
// as soon as it is sure (backend/server.py read_live). Typed sentences go in too. The other
// person is heard live on this phone (hearCall) and shown as captions from GET /api/history,
// polled while the call is on.

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

export default function Conversation() {
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
  const [hearThem, setHearThem] = useState(true);
  const endRef = useRef(null);
  const earRef = useRef(null);

  // Hold to speak, live: the server says each group of words into the call as soon as it is read
  const { videoRef, cameraOn, holding, finishing, heard, holdButton } = useLiveReader({
    onSay: (piece) => getSettings().hearMyself && playInOrder(piece),
    onDone({ text }) {
      if (!text) setError("Didn't catch that — hold the button while you mouth, or type it.");
      refresh();
    },
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

  // Their voice, live, while the call is on
  useEffect(() => {
    if (!active) return;
    const ear = hearCall();
    earRef.current = ear;
    return () => ear.close();
  }, [active]);
  useEffect(() => earRef.current?.mute(!hearThem), [hearThem, active]);

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
    send(api.sendText(text.trim(), getSettings().voice));
  }

  const turns = history.slice(fromTurn).filter((t) => t.speaker === "me" || settings.captions);

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-28 pt-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h1 className="text-lg font-extrabold">Call</h1>
        {(active || dialing) && (
          <span role="status" className="flex items-center gap-1.5 rounded-full bg-mint px-2.5 py-1 text-xs font-bold text-mint-deep dark:bg-mint-deep/25 dark:text-mint">
            <span className="size-1.5 animate-pulse rounded-full bg-mint-deep" />
            {active ? clock(seconds) : "Dialing…"}
          </span>
        )}
      </header>

      {!active ? (
        <form onSubmit={dial} className="rounded-3xl border border-line bg-card p-5 dark:border-line-dark dark:bg-panel">
          <label htmlFor="number" className="text-sm font-semibold text-muted">
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
          <p className="mt-3 text-center text-xs text-muted">They hear the words you mouth. You hear them, and read what they say.</p>
          {(error || notice) && (
            <p role="alert" className={`mt-3 text-center text-sm font-semibold ${error ? "text-red-500" : "text-muted"}`}>
              {error ?? notice}
            </p>
          )}
        </form>
      ) : (
        <>
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-3xl bg-camera shadow-xl shadow-black/20">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`absolute inset-0 size-full -scale-x-100 object-cover ${cameraOn ? "" : "hidden"}`}
            />
            <CameraChip>
              {holding
                ? "Reading your lips… release to stop"
                : finishing || busy
                  ? "Saying it…"
                  : cameraOn
                    ? "Hold the button to speak"
                    : "Tap the button for the camera"}
            </CameraChip>
            {heard && (heard.heard || heard.pending || !heard.face) && (
              <div aria-live="polite" className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/60 px-4 py-2 text-base font-semibold text-white backdrop-blur">
                {heard.face ? (
                  <>
                    {heard.heard} <span className="text-white/50">{heard.pending}</span>
                  </>
                ) : (
                  "Can't see your face — hold the phone in front of you."
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-center gap-6 py-5">
            <SideButton label={hearThem ? "Mute them" : "Hear them"} onClick={() => setHearThem((h) => !h)}>
              <Icon d={hearThem ? paths.speaker : paths.speakerOff} />
            </SideButton>
            <HoldButton holding={holding} cameraOn={cameraOn} disabled={busy || finishing} hold={holdButton} />
            <SideButton label="Hang up" onClick={hangUp} danger>
              <Icon d={paths.phone} className="size-6 rotate-[135deg]" />
            </SideButton>
          </div>

          {/* What was said on both sides, quick phrases, typing */}
          <div className="flex flex-col gap-3 rounded-3xl border border-line bg-card p-4 dark:border-line-dark dark:bg-panel">
            <div className="max-h-[36vh] min-h-24 space-y-3 overflow-y-auto">
              {turns.length === 0 && (
                <p className="py-4 text-center text-sm text-muted">Ringing… once they answer, mouth a sentence or tap a phrase.</p>
              )}
              {turns.map((t, i) => (
                <div key={i} className="flex gap-3">
                  <Avatar name={t.speaker === "me" ? "You" : "Them"} tone={t.speaker === "me" ? 0 : 1} />
                  <p className="min-w-0 break-words pt-1.5 text-base leading-relaxed text-body/90 dark:text-white/85">{t.text}</p>
                </div>
              ))}
              <div ref={endRef} />
            </div>

            {error && (
              <p role="alert" className="text-center text-sm font-semibold text-red-500">
                {error}
              </p>
            )}

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
                className="min-w-0 flex-1 rounded-xl border border-line bg-transparent px-3 py-2.5 text-base outline-none placeholder:text-muted focus:border-accent dark:border-line-dark"
              />
              <button disabled={busy} aria-label="Say it" className="rounded-xl bg-accent px-4 text-white transition hover:bg-accent-strong disabled:opacity-50">
                <Icon d={paths.send} className="size-5" />
              </button>
            </form>
          </div>
        </>
      )}
    </div>
  );
}
