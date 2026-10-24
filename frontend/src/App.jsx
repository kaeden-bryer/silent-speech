import { useEffect, useState } from "react";
import Welcome from "./screens/Welcome.jsx";
import Setup from "./screens/Setup.jsx";
import LiveCapture from "./screens/LiveCapture.jsx";
import Settings from "./screens/Settings.jsx";
// The call screen (screens/Conversation.jsx) is parked for now — kept as an
// idea for the phone-call channel, not registered in the nav.

const SCREENS = [
  { id: "welcome", label: "Welcome", component: Welcome },
  { id: "live", label: "Live", component: LiveCapture },
  { id: "setup", label: "Setup", component: Setup },
  { id: "settings", label: "Settings", component: Settings, hidden: true },
];

export default function App() {
  // #welcome / #live / #setup / #settings deep-link straight to a mockup
  const [screen, setScreen] = useState(() => {
    const hash = window.location.hash.slice(1);
    return SCREENS.some((s) => s.id === hash) ? hash : "welcome";
  });
  const [dark, setDark] = useState(false);

  useEffect(() => {
    window.location.hash = screen;
  }, [screen]);

  // Follow the browser's back/forward buttons and external hash changes
  useEffect(() => {
    const onHash = () => {
      const hash = window.location.hash.slice(1);
      if (SCREENS.some((s) => s.id === hash)) setScreen(hash);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const Active = SCREENS.find((s) => s.id === screen).component;

  return (
    <div className="app-bg h-full overflow-y-auto text-body dark:text-white">
      <Active onNavigate={setScreen} dark={dark} onToggleDark={() => setDark((d) => !d)} />

      {/* Demo-only chrome: lets the team flip between mockups and themes */}
      <div className="fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-card p-1 shadow-lg shadow-black/10 dark:border-line-dark dark:bg-panel">
        {SCREENS.filter((s) => !s.hidden).map((s) => (
          <button
            key={s.id}
            onClick={() => setScreen(s.id)}
            className={`rounded-full px-2.5 py-1.5 text-xs font-semibold transition sm:px-4 sm:text-sm ${
              screen === s.id
                ? "bg-accent text-white"
                : "text-muted hover:text-body dark:hover:text-white"
            }`}
          >
            {s.label}
          </button>
        ))}
        <button
          onClick={() => setDark((d) => !d)}
          title="Toggle dark / light"
          className="ml-1 grid size-8 place-items-center rounded-full text-muted transition hover:text-body dark:hover:text-white"
        >
          {dark ? "☀️" : "🌙"}
        </button>
      </div>
    </div>
  );
}
