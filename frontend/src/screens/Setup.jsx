import { Icon, Logo, paths } from "../components/ui.jsx";

// Setup mockup: the "Must" setup features from the research brief —
// voice cloning from a short recording, and camera/sound permission checks.
// Style: white cards, pastel icon squircles, blue for primary actions.
const PERMISSIONS = [
  { label: "Camera", detail: "to read your lips", ok: true },
  { label: "Sound", detail: "to speak for you", ok: true },
  { label: "Microphone", detail: "only while recording your voice sample", ok: false },
];

const PHRASES = [
  { text: "My name is Cara Lee", tone: "bg-blush text-blush-deep dark:bg-blush-deep/25 dark:text-blush" },
  { text: "My date of birth is March 14, 1986", tone: "bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky" },
  { text: "I pick up at the Mission St pharmacy", tone: "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint" },
];

function Card({ icon, iconTone, title, subtitle, step, children }) {
  return (
    <section className="mt-4 rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 first:mt-0 dark:border-line-dark dark:bg-panel">
      <div className="flex items-center gap-3">
        <span className={`grid size-12 shrink-0 place-items-center rounded-2xl ${iconTone}`}>
          <Icon d={icon} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-extrabold">{title}</h2>
          <p className="text-sm text-muted">{subtitle}</p>
        </div>
        {step && (
          <span className="shrink-0 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-bold text-accent-strong dark:bg-accent/15 dark:text-accent-tint">
            {step}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

export default function Setup({ onNavigate }) {
  return (
    <div className="mx-auto w-full max-w-xl px-5 pb-24 pt-6 sm:pt-10">
      <header className="mb-6 flex items-center gap-3">
        <Logo className="size-12" />
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Set up your voice</h1>
          <p className="text-sm text-muted">Two minutes, once</p>
        </div>
      </header>

      <Card
        icon={paths.mic}
        iconTone="bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint"
        title="Your voice"
        subtitle="A short recording clones it — an old voicemail works too"
        step="step 1"
      >
        {/* waveform stand-in */}
        <div className="mt-4 flex h-16 items-center gap-[3px] overflow-hidden rounded-2xl bg-paper px-3 dark:bg-panel-2">
          {Array.from({ length: 48 }, (_, i) => (
            <span
              key={i}
              className={`w-1 shrink-0 rounded-full ${i < 30 ? "bg-accent" : "bg-muted/30"}`}
              style={{ height: `${12 + 80 * Math.abs(Math.sin(i * 1.7))}%` }}
            />
          ))}
        </div>

        <div className="mt-4 flex gap-2">
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-bold text-white shadow-md shadow-accent/30 transition hover:bg-accent-strong">
            <Icon d={paths.mic} className="size-5" />
            Record 30s
          </button>
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-line py-3 text-sm font-bold text-body/70 transition hover:border-accent/40 hover:text-accent dark:border-line-dark dark:text-white/70">
            Upload a clip
          </button>
        </div>
        <p className="mt-3 text-center text-xs text-muted">
          No recording? Pick a stock voice instead.
        </p>
      </Card>

      <Card
        icon={paths.shield}
        iconTone="bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky"
        title="Permissions"
        subtitle="The browser asks once; nothing is stored"
        step="step 2"
      >
        <div className="mt-4 space-y-3">
          {PERMISSIONS.map((p) => (
            <div key={p.label} className="flex items-center gap-3">
              <span
                className={`grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-black ${
                  p.ok
                    ? "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint"
                    : "bg-paper text-muted dark:bg-panel-2"
                }`}
              >
                {p.ok ? "✓" : "…"}
              </span>
              <div className="flex-1 text-sm font-semibold">
                {p.label} <span className="font-normal text-muted">— {p.detail}</span>
              </div>
              {!p.ok && (
                <button className="rounded-full bg-accent px-3.5 py-1.5 text-sm font-bold text-white shadow-sm shadow-accent/30 transition hover:bg-accent-strong">
                  Allow
                </button>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card
        icon={paths.bookmark}
        iconTone="bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter"
        title="Your phrase bank"
        subtitle="One tap, never misread — the facts every call asks for"
      >
        <div className="mt-4 flex flex-wrap gap-2">
          {PHRASES.map((p) => (
            <span
              key={p.text}
              className={`rounded-full px-3.5 py-2 text-sm font-semibold ${p.tone}`}
            >
              {p.text}
            </span>
          ))}
          <button className="flex items-center gap-1 rounded-full border border-dashed border-muted/40 px-3.5 py-2 text-sm font-semibold text-muted transition hover:border-accent hover:text-accent">
            <Icon d={paths.plus} className="size-4" />
            Add
          </button>
        </div>
      </Card>

      <button
        onClick={() => onNavigate("live")}
        className="mt-6 w-full rounded-2xl bg-accent py-3.5 font-bold text-white shadow-lg shadow-accent/30 transition hover:bg-accent-strong"
      >
        Done — start speaking
      </button>
    </div>
  );
}
