import { useRef, useState } from "react";
import { api, playInOrder, unlockSound } from "../api.js";
import { getSettings } from "../settings.js";
import { useLiveReader } from "../useLiveReader.js";
import { CameraChip, EmotionChip, HoldButton, Icon, Logo, SideButton, paths } from "../components/ui.jsx";

// The home screen: hold the button and mouth a sentence. The lips are read live on the
// Ascent (backend/streaming.py, through useLiveReader) and each group of words is spoken as
// soon as it is sure, while you are still mouthing. Release to stop. Typing works too.

// Speak right away, unless the settings say to wait for a tap
function speaksByItself(text) {
  const s = getSettings();
  return s.autoSpeak && !(s.confirmNumbers && /\d/.test(text));
}

export default function LiveCapture() {
  const piecesRef = useRef([]); // what the server voiced during this hold
  const heldBackRef = useRef(false); // a piece waited for a tap instead of playing
  const [result, setResult] = useState(null); // {text, emotion, pieces, spoken} once said
  const [error, setError] = useState(null);
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [sending, setSending] = useState(false); // a typed sentence is on its way
  const [speaking, setSpeaking] = useState(0); // pieces playing or waiting to

  function voice(piece) {
    setSpeaking((n) => n + 1);
    playInOrder(piece, { onEnd: () => setSpeaking((n) => n - 1) });
  }

  const { videoRef, cameraOn, connected, holding, finishing, heard, mood, holdButton } = useLiveReader({
    onStart() {
      setResult(null);
      setTyping(false);
      piecesRef.current = [];
      heldBackRef.current = false;
    },
    onSay(piece) {
      piecesRef.current.push(piece);
      if (speaksByItself(piece.text)) voice(piece);
      else heldBackRef.current = true;
    },
    onDone({ text, emotion }) {
      setResult({ text, emotion, pieces: piecesRef.current, spoken: !heldBackRef.current });
      if (!text) setError("Didn't catch that. Hold the button while you mouth, with your face in view.");
    },
    onError: setError,
  });

  async function submitTyped(event) {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    unlockSound();
    setTyped("");
    setTyping(false);
    setError(null);
    setSending(true);
    try {
      const r = await api.sendText(text, getSettings().voice);
      const piece = { text: r.text, audio: r.audio };
      const spoken = Boolean(r.text) && speaksByItself(r.text);
      setResult({ text: r.text, emotion: r.emotion, pieces: [piece], spoken });
      if (spoken) voice(piece);
    } catch (err) {
      setError(`Backend error: ${err.message}`);
    } finally {
      setSending(false);
    }
  }

  function sayAgain() {
    unlockSound();
    result?.pieces.forEach(voice);
  }

  const live = holding || (finishing && heard);
  const state = holding
    ? "Reading your lips… release to stop"
    : finishing || sending
      ? "Thinking…"
      : speaking > 0
        ? "Speaking…"
        : connected
          ? "Hold the button to speak"
          : "Connecting to the Ascent…";
  const feeling = live ? mood : result?.emotion;

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-28 pt-5">
      <header className="mb-4 flex items-center gap-3">
        <Logo className="size-9" />
        <h1 className="text-lg font-extrabold">Silent Speech</h1>
      </header>

      <div className="relative aspect-[3/4] max-h-[56vh] w-full overflow-hidden rounded-3xl bg-camera shadow-xl shadow-black/20">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={`absolute inset-0 size-full -scale-x-100 object-cover ${cameraOn ? "" : "hidden"}`}
        />
        {cameraOn ? (
          <CameraChip>{state}</CameraChip>
        ) : (
          <p className="absolute inset-0 grid place-items-center px-8 text-center text-sm font-semibold text-white/60">
            Tap the button below to turn the camera on
          </p>
        )}

        {/* What is being said, then what was said */}
        {(live || result?.text) && (
          <div aria-live="polite" className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/60 px-4 py-3 backdrop-blur">
            {feeling && feeling !== "neutral" && (
              <div className="mb-1">
                <EmotionChip emotion={feeling} />
              </div>
            )}
            <p className="text-lg font-semibold leading-snug text-white">
              {live ? (
                <>
                  {heard?.heard} <span className="text-white/50">{heard?.pending}</span>
                  {!heard?.heard && !heard?.pending && "…"}
                </>
              ) : (
                result.text
              )}
            </p>
            {live && heard && !heard.face && (
              <p className="mt-1 text-xs font-semibold text-red-300">Can't see your face — hold the phone in front of you.</p>
            )}
            {!live && !result.spoken && <p className="mt-1 text-xs text-white/70">Not said yet — tap ▶ to say it.</p>}
          </div>
        )}
      </div>

      <div className="flex items-center justify-center gap-6 py-5">
        <SideButton label="Type instead" onClick={() => setTyping((t) => !t)}>
          <Icon d={paths.keyboard} />
        </SideButton>
        <HoldButton holding={holding} cameraOn={cameraOn} disabled={finishing || sending} hold={holdButton} />
        <SideButton label="Say it again" onClick={sayAgain} disabled={!result?.text || live}>
          <Icon d={paths.speaker} />
        </SideButton>
      </div>

      {typing && (
        <form onSubmit={submitTyped} className="flex gap-2">
          <input
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="Type a sentence…"
            className="min-w-0 flex-1 rounded-xl border border-line bg-card px-3 py-2.5 text-base outline-none placeholder:text-muted focus:border-accent dark:border-line-dark dark:bg-panel"
          />
          <button aria-label="Say it" className="rounded-xl bg-accent px-4 text-white transition hover:bg-accent-strong">
            <Icon d={paths.send} className="size-5" />
          </button>
        </form>
      )}

      {error && (
        <p role="alert" className="mt-2 text-center text-sm font-semibold text-red-500">
          {error}
        </p>
      )}
    </div>
  );
}
