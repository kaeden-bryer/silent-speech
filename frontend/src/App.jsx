import { useEffect, useState } from "react";
import { useSettings } from "./settings.js";
import Welcome from "./screens/Welcome.jsx";
import LiveCapture from "./screens/LiveCapture.jsx";
import Practice from "./screens/Practice.jsx";
import Settings from "./screens/Settings.jsx";
import Conversation from "./screens/Conversation.jsx";
import { Icon, paths } from "./components/ui.jsx";
// screens/Setup.jsx (voice cloning, permissions, phrase bank) is parked: see FEATURES.md.

const SCREENS = [
  { id: "welcome", component: Welcome }, // the introduction, without the tab bar
  { id: "live", label: "Speak", icon: paths.speaker, component: LiveCapture },
  { id: "call", label: "Call", icon: paths.phone, component: Conversation },
  { id: "practice", label: "Practice", icon: paths.check, component: Practice },
  { id: "settings", label: "Settings", icon: paths.settings, component: Settings },
];

export default function App() {
  // #welcome / #live / #call / #practice / #settings deep-link straight to a screen
  const [screen, setScreen] = useState(() => {
    const hash = window.location.hash.slice(1);
    return SCREENS.some((s) => s.id === hash) ? hash : "welcome";
  });
  const [settings] = useSettings();

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
    document.documentElement.classList.toggle("dark", settings.theme === "dark");
  }, [settings.theme]);

  useEffect(() => {
    document.documentElement.style.setProperty("--text-scale", settings.textScale);
  }, [settings.textScale]);

  const Active = SCREENS.find((s) => s.id === screen).component;

  return (
    <div className="app-bg h-full overflow-y-auto text-body dark:text-white">
      {/* key remounts the screen so the enter transition plays on navigation */}
      <div key={screen} className="screen-enter h-full">
        <Active onNavigate={setScreen} />
      </div>

      {screen !== "welcome" && (
        <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-line bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-line-dark dark:bg-panel/95">
          <div className="mx-auto flex max-w-md">
            {SCREENS.filter((s) => s.label).map((s) => (
              <button
                key={s.id}
                onClick={() => setScreen(s.id)}
                aria-current={screen === s.id ? "page" : undefined}
                className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-semibold transition ${
                  screen === s.id ? "text-accent" : "text-muted hover:text-body dark:hover:text-white"
                }`}
              >
                <Icon d={s.icon} className="size-6" />
                {s.label}
              </button>
            ))}
          </div>
        </nav>
      )}
    </div>
  );
}
