import { useSettings } from "../settings.js";

// Settings, stored on this phone (settings.js): the voice and when it speaks, calls, and looks.

// Kokoro voices the Ascent has (VOICES in backend/emotional_tts.py)
const VOICES = [
  { value: "am_michael", label: "Michael (male)" },
  { value: "am_fenrir", label: "Fenrir (male)" },
  { value: "am_puck", label: "Puck (male)" },
  { value: "af_heart", label: "Heart (female)" },
];

function Card({ title, children }) {
  return (
    <section className="mt-4 rounded-3xl border border-line bg-card px-5 py-3 first:mt-0 dark:border-line-dark dark:bg-panel">
      <h2 className="pt-1 text-xs font-bold tracking-widest text-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, detail, children }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="text-base font-semibold">{label}</div>
        {detail && <div className="text-xs text-muted">{detail}</div>}
      </div>
      {children}
    </div>
  );
}

function Toggle({ on, onChange, label }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-muted/30 dark:bg-panel-2"}`}
    >
      <span
        className={`absolute left-1 top-1/2 size-5 -translate-y-1/2 rounded-full bg-white shadow transition-transform ${
          on ? "translate-x-[1.25rem]" : "translate-x-0"
        }`}
      />
    </button>
  );
}

export default function Settings() {
  const [settings, update] = useSettings();

  return (
    <div className="mx-auto w-full max-w-md px-5 pb-28 pt-5">
      <h1 className="mb-4 text-lg font-extrabold">Settings</h1>

      <Card title="Voice">
        <Row label="Voice" detail="Its tone follows your face">
          <select
            value={settings.voice}
            onChange={(e) => update({ voice: e.target.value })}
            aria-label="Voice"
            className="shrink-0 rounded-full border border-line bg-transparent px-3.5 py-1.5 text-sm font-semibold outline-none focus:border-accent dark:border-line-dark"
          >
            {VOICES.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </Row>
        <Row label="Speak right away" detail="Off: wait for a tap on ▶">
          <Toggle label="Speak right away" on={settings.autoSpeak} onChange={(autoSpeak) => update({ autoSpeak })} />
        </Row>
        <Row label="Check numbers first" detail="Sentences with a number wait for a tap">
          <Toggle label="Check numbers first" on={settings.confirmNumbers} onChange={(confirmNumbers) => update({ confirmNumbers })} />
        </Row>
      </Card>

      <Card title="Calls">
        <Row label="Show what they say" detail="Captions of the other person">
          <Toggle label="Show what they say" on={settings.captions} onChange={(captions) => update({ captions })} />
        </Row>
        <Row label="Hear myself" detail="Also play your words on this phone">
          <Toggle label="Hear myself" on={settings.hearMyself} onChange={(hearMyself) => update({ hearMyself })} />
        </Row>
      </Card>

      <Card title="Display">
        <Row label="Dark mode">
          <Toggle label="Dark mode" on={settings.theme === "dark"} onChange={(dark) => update({ theme: dark ? "dark" : "light" })} />
        </Row>
        <Row label="Text size">
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
    </div>
  );
}
