import { useState } from "react";
import { Avatar, EmotionChip, Icon, Logo, paths } from "../components/ui.jsx";

// PARKED IDEA — the phone-call channel. Not registered in App's nav right now;
// kept because the sidebar + captions + quick-phrases layout is where the
// Twilio call UI would live. Re-add to SCREENS in App.jsx to bring it back.
//
// Mock data shaped like GET /api/history, so wiring it up later is mechanical.
// speaker: "me" = our user, "them" = the person on the other end.
const HISTORY = [
  { speaker: "them", name: "Pharmacy", tone: 1, text: "Mission Street Pharmacy, how can I help you?" },
  { speaker: "me", name: "You", tone: 0, text: "Hi! I'm calling to refill a prescription.", emotion: "calm" },
  { speaker: "them", name: "Pharmacy", tone: 1, text: "Sure. Can I get your name and date of birth?" },
  { speaker: "me", name: "You", tone: 0, text: "Cara Lee, March 14th, 1986.", emotion: "calm", confirmed: true },
  { speaker: "them", name: "Pharmacy", tone: 1, text: "Thank you. That'll be ready for pickup after 4pm today." },
];

const SESSIONS = [
  { name: "pharmacy", active: true },
  { name: "doctor-call" },
  { name: "team-standup" },
  { name: "mom" },
];

const QUICK_PHRASES = ["Yes", "No", "Can you repeat that?", "One moment please…"];

// Cycle pastel tones through the quick-phrase chips, like the reference design
const CHIP_TONES = [
  "bg-blush text-blush-deep dark:bg-blush-deep/25 dark:text-blush",
  "bg-sky text-sky-deep dark:bg-sky-deep/25 dark:text-sky",
  "bg-peach text-peach-deep dark:bg-peach-deep/25 dark:text-peach",
  "bg-mint text-mint-deep dark:bg-mint-deep/25 dark:text-mint",
];

export default function Conversation({ onNavigate }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex h-full">
      {/* Backdrop when the drawer is open on mobile */}
      {menuOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          onClick={() => setMenuOpen(false)}
        />
      )}

      {/* Sidebar: drawer on mobile, static column on md+ */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-80 max-w-[85vw] flex-col border-r border-line bg-card p-4 transition-transform md:static md:z-auto md:translate-x-0 dark:border-line-dark dark:bg-panel ${
          menuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-6 flex items-center gap-3 px-1">
          <Logo className="size-9 rounded-xl" />
          <div>
            <div className="text-sm font-extrabold">Silent Speech</div>
            <div className="text-xs text-muted">Your conversations</div>
          </div>
        </div>

        <SectionLabel>Conversations</SectionLabel>
        <nav className="mb-6 space-y-1">
          {SESSIONS.map((s) => (
            <a
              key={s.name}
              href="#chat"
              onClick={() => setMenuOpen(false)}
              className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold transition ${
                s.active
                  ? "bg-accent-soft text-accent-strong dark:bg-accent/15 dark:text-accent-tint"
                  : "text-muted hover:bg-paper hover:text-body dark:hover:bg-panel-2 dark:hover:text-white"
              }`}
            >
              <span className="text-base leading-none opacity-60">#</span>
              {s.name}
            </a>
          ))}
        </nav>

        <SectionLabel>Live</SectionLabel>
        <button
          onClick={() => onNavigate("live")}
          className="mb-6 flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-semibold text-muted transition hover:bg-paper hover:text-body dark:hover:bg-panel-2 dark:hover:text-white"
        >
          <Icon d={paths.camera} className="size-5.5" />
          Start live capture
        </button>

        <div className="mt-auto flex items-center gap-3 rounded-2xl bg-paper p-3 dark:bg-panel-2">
          <Avatar name="Cara L" tone={0} />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-bold">Cara</div>
            <div className="text-xs text-muted">Camera ready</div>
          </div>
          <button className="text-muted transition hover:text-body dark:hover:text-white">
            <Icon d={paths.settings} />
          </button>
        </div>
      </aside>

      {/* Chat area */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line px-4 py-3 sm:px-5 sm:py-4 dark:border-line-dark">
          <button
            onClick={() => setMenuOpen(true)}
            className="grid size-10 shrink-0 place-items-center rounded-full text-muted md:hidden"
          >
            <Icon d={paths.menu} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-extrabold">
              <span className="text-muted">#</span> pharmacy
              <span className="rounded-full bg-mint px-2 py-0.5 text-[11px] font-bold text-mint-deep dark:bg-mint-deep/25 dark:text-mint">
                on call · 1:42
              </span>
            </div>
            <div className="hidden truncate text-xs text-muted sm:block">
              Mouthed words are spoken into the call in your voice
            </div>
          </div>
          <button
            title="Speaker mode: talk to someone in the room"
            className="hidden size-10 place-items-center rounded-full text-muted transition hover:text-body sm:grid dark:hover:text-white"
          >
            <Icon d={paths.speaker} />
          </button>
          <button
            title="Hang up"
            className="grid size-10 shrink-0 place-items-center rounded-full bg-red-500 text-white shadow-md shadow-red-500/30"
          >
            <Icon d={paths.phone} className="size-5.5 rotate-[135deg]" />
          </button>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-5 sm:px-5 sm:py-6">
          {HISTORY.map((t, i) => (
            <div key={i} className="flex gap-3">
              <Avatar name={t.name} tone={t.tone} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className={`text-sm font-bold ${t.speaker === "me" ? "text-accent" : ""}`}>
                    {t.name}
                  </span>
                  {t.emotion && <EmotionChip emotion={t.emotion} />}
                  {t.confirmed && (
                    <span className="rounded-full bg-mint px-2 py-0.5 text-[11px] font-semibold text-mint-deep dark:bg-mint-deep/25 dark:text-mint">
                      ✓ confirmed
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-base leading-relaxed text-body/90 dark:text-white/85">
                  {t.text}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Quick phrases: one tap beats mouthing for the predictable turns */}
        <div className="flex gap-2 overflow-x-auto px-3 pb-2 sm:px-5 [scrollbar-width:none]">
          {QUICK_PHRASES.map((p, i) => (
            <button
              key={p}
              className={`shrink-0 rounded-full px-3.5 py-2 text-sm font-semibold transition hover:brightness-95 ${CHIP_TONES[i % CHIP_TONES.length]}`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Composer */}
        <div className="px-3 pb-20 pt-1 sm:px-5">
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-card px-2 py-2 shadow-sm dark:border-line-dark dark:bg-panel">
            <button
              onClick={() => onNavigate("live")}
              title="Speak silently on camera"
              className="grid size-11 shrink-0 place-items-center rounded-xl bg-lavender text-lavender-deep transition hover:bg-accent hover:text-white dark:bg-accent/15 dark:text-accent-tint"
            >
              <Icon d={paths.camera} />
            </button>
            <input
              placeholder="…or type a sentence instead"
              className="min-w-0 flex-1 bg-transparent px-2 text-base outline-none placeholder:text-muted"
            />
            <button className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-white shadow-accent transition hover:bg-accent-strong">
              <Icon d={paths.send} className="size-5.5" />
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div className="mb-2 flex items-center justify-between px-1 text-[11px] font-bold tracking-widest text-muted uppercase">
      {children}
      <Icon d={paths.plus} className="size-4" />
    </div>
  );
}
