import { Logo } from "../components/ui.jsx";

// The introduction: what the app does, and one button to start.
export default function Welcome({ onNavigate }) {
  return (
    <div className="grid min-h-full place-items-center px-6 py-10">
      <div className="w-full max-w-md text-center">
        <div className="relative mx-auto mb-10 grid size-[220px] place-items-center">
          <div className="absolute inset-0 rounded-full border border-line dark:border-line-dark" />
          <div className="absolute inset-8 rounded-full border border-line dark:border-line-dark" />
          <Logo className="size-20" />
        </div>

        <h1 className="text-4xl font-extrabold tracking-tight">Silent Speech</h1>
        <p className="mx-auto mt-3 max-w-xs text-base leading-relaxed text-muted">
          Mouth the words. Your phone says them out loud, as you go.
        </p>

        <button
          onClick={() => onNavigate("live")}
          className="mt-10 w-full rounded-2xl bg-accent py-3.5 text-lg font-bold text-white shadow-accent transition hover:bg-accent-strong"
        >
          Start
        </button>
      </div>
    </div>
  );
}
