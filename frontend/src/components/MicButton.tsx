import type { MicControl } from "../hooks/useVoice";

const MIC_LABEL: Record<MicControl["state"], string> = {
  off: "Mikrofon einschalten",
  connecting: "Mikrofon wird verbunden",
  ready: "Mikrofon ausschalten (wartet auf Sprache)",
  listening: "Mikrofon ausschalten (hört zu)",
  thinking: "Mikrofon ausschalten (Cat denkt nach)",
  speaking: "Mikrofon ausschalten (Cat spricht)",
};

export default function MicButton({ mic, className = "h-10 w-10 rounded-xl" }: { mic: MicControl; className?: string }) {
  const active = mic.state !== "off";
  const disabled = mic.unavailable !== null && !active;
  return (
    <button
      type="button"
      onClick={mic.toggle}
      disabled={disabled}
      aria-pressed={active}
      aria-label={MIC_LABEL[mic.state]}
      title={disabled ? (mic.unavailable ?? undefined) : MIC_LABEL[mic.state]}
      className={`grid shrink-0 place-items-center border transition ${className} disabled:cursor-not-allowed disabled:opacity-40 ${
        mic.state === "listening"
          ? "border-emerald-400 bg-emerald-500/20 text-emerald-300"
          : mic.state === "speaking"
            ? "border-amber-400 bg-amber-500/20 text-amber-300"
            : active
              ? "border-cyan-400 bg-cyan-500/20 text-cyan-300"
              : "border-cyan-400/30 text-cyan-100 hover:border-cyan-300"
      }`}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </button>
  );
}
