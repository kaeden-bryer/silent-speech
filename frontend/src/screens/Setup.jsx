import { useEffect, useState } from "react";
import { useSettings } from "../settings.js";
import { Icon, Logo, paths } from "../components/ui.jsx";

// Setup: voice cloning is demo-only until the backend grows an enrollment
// endpoint (see FEATURES.md); permissions show REAL browser states and only
// request on tap; the phrase bank is editable and persisted locally.

const CHIP_TONES = [
  "bg-blush text-blush-deep dark:bg-blush-deep/25 dark:text-blush",
  "bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky",
  "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint",
  "bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter",
  "bg-lavender text-lavender-deep dark:bg-accent/20 dark:text-lavender",
  "bg-peach text-peach-deep dark:bg-peach-deep/25 dark:text-peach",
];

function Card({ icon, iconTone, title, subtitle, step, children }) {
  return (
    <section className="mt-4 rounded-3xl border border-line bg-card p-5 shadow-sm shadow-black/5 first:mt-0 dark:border-line-dark dark:bg-panel">
      <div className="flex items-center gap-3">
        <span className={`grid size-[48px] shrink-0 place-items-center rounded-2xl ${iconTone}`}>
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

// Real browser permission states; requests happen only on tap.
function usePermissions() {
  const [perms, setPerms] = useState({ camera: "unknown", microphone: "unknown" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const next = {};
      for (const name of ["camera", "microphone"]) {
        try {
          const status = await navigator.permissions.query({ name });
          next[name] = status.state; // granted | prompt | denied
          status.onchange = () => setPerms((p) => ({ ...p, [name]: status.state }));
        } catch {
          next[name] = "unknown"; // Permissions API not supported (e.g. older Safari)
        }
      }
      if (!cancelled) setPerms((p) => ({ ...p, ...next }));
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function request(name) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        name === "camera" ? { video: true } : { audio: true },
      );
      stream.getTracks().forEach((t) => t.stop());
      setPerms((p) => ({ ...p, [name]: "granted" }));
    } catch {
      setPerms((p) => ({ ...p, [name]: "denied" }));
    }
  }

  return [perms, request];
}

function PermissionRow({ label, detail, state, onAllow }) {
  const granted = state === "granted";
  const denied = state === "denied";
  return (
    <div className="flex items-center gap-3">
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-black ${
          granted
            ? "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint"
            : denied
              ? "bg-blush text-blush-deep dark:bg-blush-deep/25 dark:text-blush"
              : "bg-paper text-muted dark:bg-panel-2"
        }`}
      >
        {granted ? "✓" : denied ? "✕" : "…"}
      </span>
      <div className="flex-1 text-sm font-semibold">
        {label} <span className="font-normal text-muted">— {detail}</span>
        {denied && (
          <div className="text-xs font-normal text-blush-deep dark:text-blush">
            Denied — enable it in your browser's site settings
          </div>
        )}
      </div>
      {!granted && !denied && onAllow && (
        <button
          onClick={onAllow}
          className="rounded-full bg-accent px-3.5 py-1.5 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong"
        >
          Allow
        </button>
      )}
    </div>
  );
}

export default function Setup({ onNavigate }) {
  const [settings, update] = useSettings();
  const [perms, requestPermission] = usePermissions();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const soundAvailable = "speechSynthesis" in window;

  function addPhrase(event) {
    event.preventDefault();
    const text = draft.trim();
    if (text) update({ phrases: [...settings.phrases, text] });
    setDraft("");
    setAdding(false);
  }

  function removePhrase(text) {
    update({ phrases: settings.phrases.filter((p) => p !== text) });
  }

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
        {/* waveform stand-in; voice cloning is demo-only until the backend has it */}
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
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-bold text-white shadow-accent transition hover:bg-accent-strong">
            <Icon d={paths.mic} className="size-5" />
            Record 30s
          </button>
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-line py-3 text-sm font-bold text-body/70 transition hover:border-accent/40 hover:text-accent dark:border-line-dark dark:text-white/70">
            Upload a clip
          </button>
        </div>
        <p className="mt-3 text-center text-xs text-muted">
          Demo only for now — the app speaks with a standard voice until voice
          cloning is connected.
        </p>
      </Card>

      <Card
        icon={paths.shield}
        iconTone="bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky"
        title="Permissions"
        subtitle="Asked only when needed; nothing is stored"
        step="step 2"
      >
        <div className="mt-4 space-y-3">
          <PermissionRow
            label="Camera"
            detail="to read your lips"
            state={perms.camera}
            onAllow={() => requestPermission("camera")}
          />
          <PermissionRow
            label="Sound"
            detail="to speak for you"
            state={soundAvailable ? "granted" : "denied"}
          />
          <PermissionRow
            label="Microphone"
            detail="only while recording your voice sample"
            state={perms.microphone}
            onAllow={() => requestPermission("microphone")}
          />
        </div>
      </Card>

      <Card
        icon={paths.bookmark}
        iconTone="bg-butter text-butter-deep dark:bg-butter-deep/25 dark:text-butter"
        title="Your phrase bank"
        subtitle="One tap, never misread — the facts every call asks for"
      >
        <div className="mt-4 flex flex-wrap gap-2">
          {settings.phrases.map((p, i) => (
            <span
              key={p}
              className={`flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-semibold ${CHIP_TONES[i % CHIP_TONES.length]}`}
            >
              {p}
              <button
                aria-label={`Remove phrase: ${p}`}
                onClick={() => removePhrase(p)}
                className="opacity-60 transition hover:opacity-100"
              >
                ✕
              </button>
            </span>
          ))}
          {adding ? (
            <form onSubmit={addPhrase} className="flex items-center gap-1">
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={addPhrase}
                placeholder="New phrase…"
                className="w-48 rounded-full border border-accent bg-transparent px-3.5 py-2 text-sm font-semibold outline-none placeholder:text-muted"
              />
            </form>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="flex items-center gap-1 rounded-full border border-dashed border-muted/40 px-3.5 py-2 text-sm font-semibold text-muted transition hover:border-accent hover:text-accent"
            >
              <Icon d={paths.plus} className="size-4" />
              Add
            </button>
          )}
        </div>
      </Card>

      <button
        onClick={() => onNavigate("live")}
        className="mt-6 w-full rounded-2xl bg-accent py-3.5 font-bold text-white shadow-accent transition hover:bg-accent-strong"
      >
        Done — start speaking
      </button>
    </div>
  );
}
