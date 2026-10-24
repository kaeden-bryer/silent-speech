import { useSettings } from "../settings.js";
import { Icon, paths } from "../components/ui.jsx";

// Settings, wired client-side only (the backend isn't finished):
// theme + text size apply globally, auto-speak / confirm-numbers / smoothing
// change how the live screen behaves. Call-channel toggles persist but do
// nothing until the call screen returns (see FEATURES.md).

function Card({ icon, iconTone, title, children }) {
  return (
    <section className="mt-4 rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 first:mt-0 dark:border-line-dark dark:bg-panel">
      <div className="mb-4 flex items-center gap-3">
        <span className={`grid size-[46px] shrink-0 place-items-center rounded-2xl ${iconTone}`}>
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

function Toggle({ on, onChange }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${
        on ? "bg-accent" : "bg-muted/30 dark:bg-panel-2"
      }`}
    >
      <span
        className={`absolute top-1 size-5 rounded-full bg-white shadow transition-all ${
          on ? "left-6" : "left-1"
        }`}
      />
    </button>
  );
}

function Segmented({ options, value, onChange }) {
  return (
    <div className="flex shrink-0 rounded-full border border-line p-1 dark:border-line-dark">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-3.5 py-1.5 text-sm font-semibold transition ${
            o.value === value
              ? "bg-accent text-white"
              : "text-muted hover:text-body dark:hover:text-white"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function Settings({ onNavigate }) {
  const [settings, update] = useSettings();

  return (
    <div className="mx-auto w-full max-w-xl px-5 pb-24 pt-6 sm:pt-10">
      <header className="mb-6 flex items-center gap-3">
        <button
          onClick={() => onNavigate("live")}
          aria-label="Back to live capture"
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
          <Segmented
            options={[
              { value: "light", label: "Light" },
              { value: "dark", label: "Dark" },
            ]}
            value={settings.theme}
            onChange={(theme) => update({ theme })}
          />
        </Row>
        <Row label="Text size" detail="Everything scales together">
          <div className="flex items-center gap-2 text-muted">
            <span className="text-xs font-bold">A</span>
            <input
              type="range"
              min="0.85"
              max="1.3"
              step="0.05"
              value={settings.textScale}
              onChange={(e) => update({ textScale: Number(e.target.value) })}
              className="w-28 accent-accent"
              aria-label="Text size"
            />
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
        <Row label="Auto-speak" detail="Speak right away when a result arrives">
          <Toggle on={settings.autoSpeak} onChange={(autoSpeak) => update({ autoSpeak })} />
        </Row>
        <Row label="Confirm numbers first" detail="Results with digits wait for a tap">
          <Toggle on={settings.confirmNumbers} onChange={(confirmNumbers) => update({ confirmNumbers })} />
        </Row>
      </Card>

      <Card
        icon={paths.keyboard}
        iconTone="bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky"
        title="Captions & calls"
      >
        <p className="-mt-2 mb-2 text-xs text-muted">
          Saved now, used once phone calls land (see FEATURES.md).
        </p>
        <Row label="Live captions" detail="Show what the other person says">
          <Toggle on={settings.captions} onChange={(captions) => update({ captions })} />
        </Row>
        <Row label="Opening line" detail='"Hi — I speak through an app, one moment"'>
          <Toggle on={settings.openingLine} onChange={(openingLine) => update({ openingLine })} />
        </Row>
        <Row label="Hold-on filler" detail="Plays while you mouth your reply">
          <Toggle on={settings.filler} onChange={(filler) => update({ filler })} />
        </Row>
      </Card>

      <Card
        icon={paths.bookmark}
        iconTone="bg-peach text-peach-deep dark:bg-peach-deep/25 dark:text-peach"
        title="Phrase bank"
      >
        <Row label={`${settings.phrases.length} saved phrase${settings.phrases.length === 1 ? "" : "s"}`} detail="One tap, never misread">
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
