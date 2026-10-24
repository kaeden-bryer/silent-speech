import { useEffect, useState } from "react";
import Welcome from "./screens/Welcome.jsx";
import Setup from "./screens/Setup.jsx";
import Conversation from "./screens/Conversation.jsx";
import LiveCapture from "./screens/LiveCapture.jsx";

const SCREENS = [
  { id: "welcome", label: "Welcome", component: Welcome },
  { id: "setup", label: "Setup", component: Setup },
  { id: "chat", label: "Call", component: Conversation },
  { id: "live", label: "Live capture", component: LiveCapture },
];

export default function App() {
  // #welcome / #chat / #live deep-link straight to a mockup
  const [screen, setScreen] = useState(() => {
    const hash = window.location.hash.slice(1);
    return SCREENS.some((s) => s.id === hash) ? hash : "welcome";
  });
  const [dark, setDark] = useState(false);

  useEffect(() => {
    window.location.hash = screen;
  }, [screen]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const Active = SCREENS.find((s) => s.id === screen).component;

  return (
    <div className="app-bg h-full overflow-y-auto text-body dark:text-white">
      <Active onNavigate={setScreen} />

      {/* Demo-only chrome: lets the team flip between mockups and themes */}
      <div className="fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-card p-1 shadow-lg shadow-black/10 dark:border-line-dark dark:bg-panel">
        {SCREENS.map((s) => (
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
