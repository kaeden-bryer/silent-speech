import { Avatar, Logo } from "../components/ui.jsx";

// Orbiting "people" around the logo, like the Andx welcome screen.
const ORBIT = [
  { name: "Maya K", tone: 1, ring: 110, angle: 20 },
  { name: "Sam O", tone: 2, ring: 110, angle: 150 },
  { name: "Jo Lin", tone: 3, ring: 110, angle: 265 },
  { name: "Ana R", tone: 4, ring: 170, angle: 75 },
  { name: "Dev P", tone: 0, ring: 170, angle: 200 },
  { name: "Kai T", tone: 2, ring: 170, angle: 330 },
];

export default function Welcome({ onNavigate }) {
  return (
    <div className="grid min-h-full place-items-center px-6 py-10">
      <div className="w-full max-w-md text-center">
        <div className="relative mx-auto mb-4 grid h-[260px] w-full place-items-center sm:mb-8 sm:h-[380px]">
          <div className="grid scale-70 place-items-center sm:scale-100">
            {/* orbit rings */}
            <div className="absolute size-[220px] rounded-full border border-line dark:border-line-dark" />
            <div className="absolute size-[340px] rounded-full border border-line dark:border-line-dark" />

            <Logo className="size-16" />

            {ORBIT.map((p) => {
              const rad = (p.angle * Math.PI) / 180;
              const x = Math.cos(rad) * p.ring;
              const y = Math.sin(rad) * p.ring;
              return (
                <div
                  key={p.name}
                  className="absolute"
                  style={{ transform: `translate(${x}px, ${y}px)` }}
                >
                  <Avatar name={p.name} tone={p.tone} size="size-10" />
                </div>
              );
            })}
          </div>
        </div>

        <h1 className="text-4xl font-extrabold tracking-tight">
          Your voice, anywhere
        </h1>
        <p className="mx-auto mt-3 max-w-sm text-base leading-relaxed text-muted">
          Mouth words at the camera and they're spoken aloud in your own
          voice — on phone calls, in person, or in a meeting.
        </p>

        <button
          onClick={() => onNavigate("setup")}
          className="mt-8 w-full rounded-2xl bg-accent py-3.5 font-bold text-white shadow-lg shadow-accent/30 transition hover:bg-accent-strong"
        >
          Set up your voice
        </button>
        <button
          onClick={() => onNavigate("chat")}
          className="mt-3 w-full rounded-2xl py-3 text-sm font-semibold text-muted transition hover:text-body dark:hover:text-white"
        >
          Try a call first
        </button>
      </div>
    </div>
  );
}
