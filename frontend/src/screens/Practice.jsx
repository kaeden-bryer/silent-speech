import { useEffect, useReducer, useRef, useState } from "react";
import { api, play, speak, unlockSound } from "../api.js";
import { CameraChip, HoldButton, Icon, SideButton, paths } from "../components/ui.jsx";
import { PHRASES, initialState, practiceReducer } from "../practice.js";

// Practice mode: mouth the shown phrase, the lip reader reads it back, and
// each word is marked matched (mint, check + underline) or missed (blush,
// strikethrough + what was read instead). Calm and encouraging, not clinical.
//
// Recognition reuses POST /api/video (the raw lip-reading, before correction —
// correction would "fix" the attempt and defeat the practice). If the backend
// is unreachable the result falls back to a clearly labeled demo fixture.

const DEMO_FIXTURE = "I need more coffee.";

export default function Practice() {
  const [state, dispatch] = useReducer(practiceReducer, initialState);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");

  const phrase = PHRASES[state.phraseIndex];
  const target = phrase.text;
  const { phase, result, error } = state;

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false, // practice never needs the microphone
        video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 25 } },
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setCameraOn(true);
    } catch (err) {
      dispatch({
        type: "ERROR",
        kind: "camera",
        message: `Camera unavailable: ${err.message}. Phones need HTTPS — or use the keyboard to practice.`,
      });
    }
  }

  // Hold to speak, like the other screens: recording while the button is held
  function press() {
    unlockSound();
    if (!cameraOn) return void startCamera();
    if (phase === "recording" || phase === "processing") return;
    const chunks = [];
    const rec = new MediaRecorder(streamRef.current);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = () => {
      dispatch({ type: "RECORD_STOP" });
      recognize(new Blob(chunks, { type: rec.mimeType }));
    };
    recorderRef.current = rec;
    rec.start();
    dispatch({ type: "RECORD_START" });
  }

  function release() {
    unlockSound(); // iPhones count lifting the finger as a tap, not touching down
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  const hold = {
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

  async function recognize(clip) {
    try {
      const r = await api.sendVideo(clip);
      const recognized = r.raw_text || r.text;
      if (!recognized) {
        dispatch({
          type: "ERROR",
          kind: "recognition",
          message: "We couldn't read that — face the camera and try again, or type what you mouthed.",
        });
        return;
      }
      dispatch({ type: "RESULT", recognized, source: "lipread" });
    } catch {
      // Backend unreachable: labeled demo result so the flow stays reviewable
      dispatch({ type: "RESULT", recognized: DEMO_FIXTURE, source: "demo" });
    }
  }

  function submitTyped(event) {
    event.preventDefault();
    const text = typed.trim();
    if (!text) return;
    unlockSound();
    setTyped("");
    setTyping(false);
    dispatch({ type: "PROCESS" });
    dispatch({ type: "RESULT", recognized: text, source: "typed" });
  }

  const recording = phase === "recording";
  const processing = phase === "processing";
  const score = result?.score;

  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-28 pt-5">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h1 className="text-lg font-extrabold">Practice</h1>
        <span className="shrink-0 rounded-full bg-lavender px-2.5 py-1 text-xs font-bold text-lavender-deep dark:bg-accent/20 dark:text-lavender">
          {state.phraseIndex + 1} / {PHRASES.length}
        </span>
      </header>

      <div className="flex flex-col gap-4">
        {/* Camera + controls */}
        <div className="flex flex-col">
          <div className="relative aspect-[3/4] max-h-[44vh] w-full overflow-hidden rounded-3xl bg-camera shadow-xl shadow-black/20">
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
                  onClick={startCamera}
                  className="flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong"
                >
                  <Icon d={paths.camera} className="size-5" />
                  Start camera
                </button>
              </div>
            )}
            {cameraOn && (
              <CameraChip>
                {recording ? "Reading your lips… release to stop" : processing ? "Thinking…" : "Hold the button and mouth the phrase"}
              </CameraChip>
            )}
          </div>

          <div className="flex items-center justify-center gap-6 py-5">
            <SideButton label="Type instead" onClick={() => setTyping((t) => !t)}>
              <Icon d={paths.keyboard} />
            </SideButton>
            <HoldButton holding={recording} cameraOn={cameraOn} disabled={processing} hold={hold} />
            <SideButton
              label="Replay your attempt"
              disabled={!result}
              onClick={() => {
                unlockSound();
                play({ text: result.recognized, audio: null });
              }}
            >
              <Icon d={paths.speaker} />
            </SideButton>
          </div>
        </div>

        {/* Phrase + result (above the camera) */}
        <div className="order-first flex flex-col gap-4">
          {/* Target phrase: visible in every state */}
          <div className="rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 dark:border-line-dark dark:bg-panel">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="text-[11px] font-bold tracking-widest text-muted uppercase">Your phrase</span>
                <span className="rounded-full bg-sky px-2 py-0.5 text-[11px] font-semibold text-sky-deep dark:bg-sky-deep/25 dark:text-sky">
                  {phrase.category}
                </span>
              </span>
              <button
                aria-label="Hear the phrase"
                onClick={() => {
                  unlockSound();
                  speak(target);
                }}
                className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-strong transition hover:bg-accent hover:text-white dark:bg-accent/15 dark:text-accent-tint"
              >
                <Icon d={paths.speaker} className="size-4.5" />
              </button>
            </div>
            <p className="text-[1.5rem] font-extrabold leading-snug tracking-tight">{target}</p>
            {!result && (
              <div className="mt-1 flex justify-end">
                <button
                  onClick={() => dispatch({ type: "NEXT" })}
                  className="rounded-full px-2 py-1 text-sm font-semibold text-muted transition hover:text-accent"
                >
                  Skip →
                </button>
              </div>
            )}
          </div>

          {/* Result card */}
          {(result || error || processing) && (
            <div aria-live="polite" className="rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 dark:border-line-dark dark:bg-panel">
              {result ? (
                <>
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[11px] font-bold tracking-widest text-muted uppercase">What we read</span>
                    {result.source !== "lipread" && (
                      <span className="rounded-full bg-butter px-2 py-0.5 text-[11px] font-bold text-butter-deep dark:bg-butter-deep/25 dark:text-butter">
                        {result.source === "demo" ? "demo result — backend offline" : "typed"}
                      </span>
                    )}
                  </div>

                  <p className="text-base font-extrabold">
                    {score.perfect ? "Perfect! 🎉" : `${score.matched} of ${score.total} words — ${score.matched > 0 ? "almost!" : "keep trying!"}`}
                  </p>
                  <div
                    role="progressbar"
                    aria-valuenow={score.percent}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${score.matched} of ${score.total} words matched`}
                    className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-accent-soft dark:bg-panel-2"
                  >
                    <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${score.percent}%` }} />
                  </div>

                  {/* Word tokens: shape (check / strikethrough) as well as color */}
                  <div className="mt-4 flex flex-wrap gap-2">
                    {score.tokens.map((t, i) =>
                      t.matched ? (
                        <span
                          key={i}
                          className="flex items-center gap-1 rounded-full bg-mint px-3 py-1.5 text-sm font-semibold text-mint-deep underline decoration-2 underline-offset-4 dark:bg-mint-deep/25 dark:text-mint"
                        >
                          <Icon d={paths.check} className="size-4 shrink-0" />
                          {t.word}
                        </span>
                      ) : (
                        <span
                          key={i}
                          className="flex items-center gap-1.5 rounded-full bg-blush px-3 py-1.5 text-sm font-semibold text-blush-deep dark:bg-blush-deep/25 dark:text-blush"
                        >
                          <s>{t.word}</s>
                          <span className="text-xs font-bold">read: {t.read ?? "—"}</span>
                        </span>
                      ),
                    )}
                  </div>

                  <div className="mt-4 flex gap-2">
                    <button
                      onClick={() => dispatch({ type: score.perfect ? "NEXT" : "RETRY" })}
                      className="flex-1 rounded-xl bg-accent py-3 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong"
                    >
                      {score.perfect ? "Next phrase →" : "Try again"}
                    </button>
                    <button
                      onClick={() => dispatch({ type: score.perfect ? "RETRY" : "NEXT" })}
                      className="flex-1 rounded-xl border border-line py-3 text-sm font-bold text-body/70 transition hover:border-accent/40 hover:text-accent dark:border-line-dark dark:text-white/70"
                    >
                      {score.perfect ? "Try again" : "Next phrase →"}
                    </button>
                  </div>
                  {!score.perfect && (
                    <button
                      onClick={() => {
                        unlockSound();
                        speak(`The phrase was: ${target}. We read: ${result.recognized}`);
                      }}
                      className="mt-2 w-full py-1 text-center text-sm font-semibold text-muted transition hover:text-body dark:hover:text-white"
                    >
                      Hear the difference
                    </button>
                  )}
                </>
              ) : processing ? (
                <p className="py-4 text-center text-sm text-muted">Reading your attempt…</p>
              ) : (
                <p role="alert" className="py-2 text-center text-sm font-semibold text-blush-deep dark:text-blush">
                  {error.message}
                </p>
              )}
            </div>
          )}

          {typing && (
            <form onSubmit={submitTyped} className="flex gap-2">
              <input
                autoFocus
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder="Type what you mouthed…"
                className="min-w-0 flex-1 rounded-xl border border-line bg-card px-3 py-2.5 text-base outline-none placeholder:text-muted focus:border-accent dark:border-line-dark dark:bg-panel"
              />
              <button aria-label="Check my attempt" className="rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong">
                <Icon d={paths.send} className="size-5" />
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
