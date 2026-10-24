import { Icon, Logo, paths } from "../components/ui.jsx";

// Settings mockup: appearance is real (theme comes from App); the rest are
// placeholders for the controls the research brief suggests users will want.

function Card({ icon, iconTone, title, children }) {
  return (
    <section className="mt-4 rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 first:mt-0 dark:border-line-dark dark:bg-panel">
      <div className="mb-4 flex items-center gap-3">
        <span className={`grid size-11 shrink-0 place-items-center rounded-2xl ${iconTone}`}>
          <Icon d={icon} className="size-5.5" />
        </span>
        <h2 className="text-base font-extrabold">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Row({ label, detail, children }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{label}</div>
        {detail && <div className="text-xs text-muted">{detail}</div>}
      </div>
      {children}
    </div>
  );
}

function Toggle({ on }) {
  return (
    <span
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${
        on ? "bg-accent" : "bg-muted/30 dark:bg-panel-2"
      }`}
    >
      <span
        className={`absolute top-1 size-5 rounded-full bg-white shadow transition-all ${
          on ? "left-6" : "left-1"
        }`}
      />
    </span>
  );
}

export default function Settings({ onNavigate, dark, onToggleDark }) {
  return (
    <div className="mx-auto w-full max-w-xl px-5 pb-24 pt-6 sm:pt-10">
      <header className="mb-6 flex items-center gap-3">
        <button
          onClick={() => onNavigate("live")}
          className="grid size-10 place-items-center rounded-full border border-line text-muted transition hover:text-body dark:border-line-dark dark:hover:text-white"
        >
          <Icon d={paths.back} className="size-5.5" />
        </button>
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Settings</h1>
          <p className="text-sm text-muted">Make it yours</p>
        </div>
      </header>

      <Card
        icon={paths.settings}
        iconTone="bg-lavender text-lavender-deep dark:bg-accent/20 dark:text-lavender"
        title="Appearance"
      >
        <Row label="Theme" detail="Light works best in bright rooms">
          <div className="flex rounded-full border border-line p-1 dark:border-line-dark">
            {["Light", "Dark"].map((t) => {
              const active = (t === "Dark") === dark;
              return (
                <button
                  key={t}
                  onClick={() => active || onToggleDark()}
                  className={`rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                    active ? "bg-accent text-white" : "text-muted hover:text-body dark:hover:text-white"
                  }`}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </Row>
        <Row label="Text size" detail="Everything scales together">
          <div className="flex items-center gap-2 text-muted">
            <span className="text-xs font-bold">A</span>
            <span className="relative h-1.5 w-28 rounded-full bg-muted/30">
              <span className="absolute left-0 top-0 h-full w-2/3 rounded-full bg-accent" />
              <span className="absolute left-2/3 top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow ring-1 ring-line" />
            </span>
            <span className="text-lg font-bold">A</span>
          </div>
        </Row>
      </Card>

      <Card
        icon={paths.speaker}
        iconTone="bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint"
        title="Speaking"
      >
        <Row label="Your voice" detail="Cloned from your recording">
          <button
            onClick={() => onNavigate("setup")}
            className="rounded-full bg-accent-soft px-3.5 py-1.5 text-sm font-bold text-accent-strong transition hover:bg-accent hover:text-white dark:bg-accent/15 dark:text-accent-tint"
          >
            Change
          </button>
        </Row>
        <Row label="Auto-speak" detail="Speak right away when confidence is high">
          <Toggle on />
        </Row>
        <Row label="Confirm numbers first" detail="Dates, doses and addresses wait for a tap">
          <Toggle on />
        </Row>
        <Row label="Smoothing" detail="How much the app tidies your sentences">
          <span className="rounded-full bg-butter px-3 py-1 text-xs font-bold text-butter-deep dark:bg-butter-deep/25 dark:text-butter">
            Light
          </span>
        </Row>
      </Card>

      <Card
        icon={paths.keyboard}
        iconTone="bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky"
        title="Captions & calls"
      >
        <Row label="Live captions" detail="Show what the other person says">
          <Toggle on />
        </Row>
        <Row label="Opening line" detail='"Hi — I speak through an app, one moment"'>
          <Toggle on />
        </Row>
        <Row label="Hold-on filler" detail="Plays while you mouth your reply">
          <Toggle on={false} />
        </Row>
      </Card>

      <Card
        icon={paths.bookmark}
        iconTone="bg-peach text-peach-deep dark:bg-peach-deep/25 dark:text-peach"
        title="Phrase bank"
      >
        <Row label="3 saved phrases" detail="Name, date of birth, pharmacy">
          <button
            onClick={() => onNavigate("setup")}
            className="rounded-full bg-accent-soft px-3.5 py-1.5 text-sm font-bold text-accent-strong transition hover:bg-accent hover:text-white dark:bg-accent/15 dark:text-accent-tint"
          >
            Edit
          </button>
        </Row>
      </Card>
    </div>
  );
}
