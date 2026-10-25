// Small shared pieces for the screens. Purely presentational.

export function Logo({ className = "size-10" }) {
  return (
    <div
      className={`grid place-items-center rounded-2xl bg-gradient-to-br from-[#8ba1e2] to-accent text-white shadow-accent ${className}`}
    >
      <svg viewBox="0 0 24 24" fill="none" className="size-1/2" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
        {/* lips / soundwave mark */}
        <path d="M3 12h2.5l2-5 3 10 3-8 2 3H21" />
      </svg>
    </div>
  );
}

const AVATAR_TONES = [
  "bg-blush text-blush-deep",
  "bg-sky text-sky-deep",
  "bg-mint text-mint-deep",
  "bg-peach text-peach-deep",
  "bg-lavender text-lavender-deep",
  "bg-butter text-butter-deep",
];

export function Avatar({ name, size = "size-9", tone = 0 }) {
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <div
      className={`grid shrink-0 place-items-center rounded-full text-xs font-bold ${size} ${AVATAR_TONES[tone % AVATAR_TONES.length]}`}
    >
      {initials}
    </div>
  );
}

export function EmotionChip({ emotion }) {
  return (
    <span className="rounded-full bg-blush px-2 py-0.5 text-[11px] font-semibold text-blush-deep dark:bg-blush-deep/25 dark:text-blush">
      {emotion}
    </span>
  );
}

// The one status line on a camera preview ("Hold the button to speak", "Reading your lips…")
export function CameraChip({ children }) {
  return (
    <div className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-xs font-bold text-white backdrop-blur">
      {children}
    </div>
  );
}

// The big round hold-to-speak button. `hold`: the pointer handlers (see useLiveReader.js).
export function HoldButton({ holding, cameraOn, disabled, hold }) {
  const label = holding ? "Release to stop" : cameraOn ? "Hold to speak" : "Start camera";
  return (
    <button
      title={label}
      aria-label={label}
      aria-pressed={holding}
      disabled={disabled && !holding}
      {...hold}
      className={`grid size-[80px] touch-none select-none place-items-center rounded-full text-white ring-4 transition [-webkit-touch-callout:none] disabled:opacity-50 ${
        holding
          ? "scale-110 bg-red-500 shadow-xl shadow-red-500/40 ring-red-500/30"
          : "bg-accent shadow-accent ring-accent/20 hover:bg-accent-strong"
      }`}
    >
      {holding ? (
        <span className="size-7 animate-pulse rounded-lg bg-white" />
      ) : (
        <Icon d={cameraOn ? paths.speaker : paths.camera} className="size-8" />
      )}
    </button>
  );
}

// A smaller round button next to it (keyboard, replay, hang up...)
export function SideButton({ label, onClick, disabled, danger, children }) {
  return (
    <button
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={`grid size-[56px] place-items-center rounded-full transition disabled:opacity-40 ${
        danger
          ? "bg-red-500 text-white shadow-md shadow-red-500/30 hover:bg-red-600"
          : "border border-line text-muted hover:text-body dark:border-line-dark dark:hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

export function Icon({ d, className = "size-6" }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d={d} />
    </svg>
  );
}

export const paths = {
  menu: "M4 7h16M4 12h10M4 17h16",
  search: "M21 21l-4.3-4.3M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0z",
  camera: "M15.6 6H8.4L7 8H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V9a1 1 0 0 0-1-1h-3l-1.4-2zM12 16.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4z",
  send: "M5 12h13M13 6l6 6-6 6",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  speaker: "M4 10v4h3l5 4V6l-5 4H4zm12-1a4 4 0 0 1 0 6m2.5-9a8 8 0 0 1 0 12",
  speakerOff: "M4 10v4h3l5 4V6l-5 4H4zm12 0 5 5m0-5-5 5",
  plus: "M12 5v14M5 12h14",
  mic: "M12 3a3 3 0 0 1 3 3v5a3 3 0 1 1-6 0V6a3 3 0 0 1 3-3zM6 11a6 6 0 0 0 12 0M12 17v4",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm8 3a8 8 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a8 8 0 0 0-2-1.2L15 3h-4l-.4 2.6a8 8 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a8 8 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a8 8 0 0 0 2 1.2L11 21h4l.4-2.6a8 8 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.2-.8.2-1.2z",
  back: "M15 18l-6-6 6-6",
  shield: "M12 3l7 3v5c0 4.4-3 8.4-7 10-4-1.6-7-5.6-7-10V6l7-3zM9 12l2 2 4-4",
  check: "M5 13l4 4L19 7",
  bookmark: "M7 4h10a1 1 0 0 1 1 1v16l-6-4-6 4V5a1 1 0 0 1 1-1z",
  keyboard: "M4 7h16a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm3 3h0m4 0h0m4 0h0m-8 4h6",
};
