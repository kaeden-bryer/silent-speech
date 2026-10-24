import { Icon, Logo, paths } from "../components/ui.jsx";

// The app's home screen: mouth a sentence, pick what you said, it's spoken
// aloud. One engine, several output channels (speaker, phone call, meeting).
// Top-3 pick is the trust point from the research brief; candidates mock the
// backend's demo_phrases.txt.
const CANDIDATES = [
  { text: "I need more caffeine.", confidence: "92%", picked: true },
  { text: "I need more coffee in.", confidence: "78%" },
  { text: "I knead more caffeine.", confidence: "41%" },
];

const CHANNELS = [
  { label: "Speaker", icon: paths.speaker, active: true },
  { label: "Phone call", icon: paths.phone },
  { label: "Meeting", icon: paths.camera },
];

export default function LiveCapture({ onNavigate }) {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-md flex-col px-5 pb-24 pt-5 md:max-w-5xl">
      <header className="mb-4 flex items-center gap-3">
        <Logo className="size-10" />
        <div className="flex-1">
          <div className="text-base font-extrabold">Silent Speech</div>
          <div className="text-sm text-muted">Speaker mode — speaks out loud on this device</div>
        </div>
        <span className="flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-[11px] font-bold text-red-500">
          <span className="size-1.5 animate-pulse rounded-full bg-red-500" />
          READING
        </span>
        <button
          title="Settings"
          onClick={() => onNavigate("settings")}
          className="grid size-10 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
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
          {/* stand-in for the <video> element */}
          <div className="absolute inset-0 grid place-items-center">
            <svg viewBox="0 0 200 260" className="w-1/2 text-muted/40" fill="none" stroke="currentColor" strokeWidth="3">
              <ellipse cx="100" cy="100" rx="55" ry="70" />
              <path d="M80 125 q20 14 40 0" strokeLinecap="round" />
              <circle cx="82" cy="88" r="4" fill="currentColor" stroke="none" />
              <circle cx="118" cy="88" r="4" fill="currentColor" stroke="none" />
            </svg>
          </div>

          {/* lip-tracking frame */}
          <div className="absolute left-1/2 top-[46%] h-9 w-20 -translate-x-1/2 rounded-xl border-2 border-accent/80" />

          {/* status: users can't hear themselves, so the UI has to say it */}
          <div className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-[11px] font-bold text-white backdrop-blur">
            Face visible ✓
          </div>

          {/* live partial transcript */}
          <div className="absolute inset-x-3 bottom-3 rounded-2xl bg-black/55 px-4 py-2.5 backdrop-blur">
            <div className="text-[10px] font-bold tracking-widest text-white/50 uppercase">
              Reading…
            </div>
            <div className="text-sm font-semibold text-white">
              i need more caffe…
            </div>
          </div>
        </div>

        {/* Candidates + confirm */}
        <div className="flex flex-col gap-3 md:w-[26rem] md:shrink-0">
          <div className="rounded-2xl border border-line bg-card p-4 dark:border-line-dark dark:bg-panel">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-bold tracking-widest text-muted uppercase">
                Did you say…
              </span>
            </div>

            <div className="space-y-2">
              {CANDIDATES.map((c) => (
                <button
                  key={c.text}
                  className={`flex w-full items-center justify-between rounded-xl border px-3.5 py-3 text-left text-base font-semibold transition ${
                    c.picked
                      ? "border-accent bg-accent-soft text-accent-strong dark:bg-accent/15 dark:text-accent-tint"
                      : "border-line text-body/80 hover:border-accent/50 dark:border-line-dark dark:text-white/80"
                  }`}
                >
                  <span>{c.text}</span>
                  <span className={`text-xs ${c.picked ? "" : "text-muted"}`}>{c.confidence}</span>
                </button>
              ))}
            </div>

            <button className="mt-3 w-full rounded-xl bg-accent py-3 text-base font-bold text-white shadow-md shadow-accent/30 transition hover:bg-accent-strong">
              Speak it — "I need more caffeine."
            </button>
            <button className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-line py-2.5 text-sm font-bold text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white">
              <Icon d={paths.keyboard} className="size-5" />
              None of these — type it
            </button>
            <p className="mt-3 text-center text-xs text-muted">
              Dates, numbers and addresses always need a tap before they're spoken.
            </p>
          </div>

          {/* Record controls */}
          <div className="flex items-center justify-center gap-8 py-2">
            <button
              title="Keyboard fallback"
              className="grid size-14 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.keyboard} />
            </button>
            <button
              title="Stop reading"
              className="grid size-18 place-items-center rounded-full bg-accent text-white shadow-xl shadow-accent/40 ring-4 ring-accent/20 transition hover:bg-accent-strong"
            >
              <span className="size-6 rounded-md bg-white" />
            </button>
            <button
              title="Replay last sentence"
              className="grid size-14 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
            >
              <Icon d={paths.speaker} />
            </button>
          </div>
          <p className="-mt-2 text-center text-xs text-muted">
            Mouth one sentence, then tap to stop
          </p>
        </div>
      </div>
    </div>
  );
}
