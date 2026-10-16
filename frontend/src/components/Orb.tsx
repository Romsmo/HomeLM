import type { VoiceStateName } from "../protocol";

const LABEL: Record<VoiceStateName, string> = {
  idle: "Cat wartet",
  listening: "Cat hört zu",
  thinking: "Cat denkt nach",
  speaking: "Cat spricht",
};

export default function Orb({ state, size = "large" }: { state: VoiceStateName; size?: "large" | "small" }) {
  return (
    <div className="flex flex-col items-center gap-6">
      <div
        className="orb"
        data-state={state}
        role="img"
        aria-label={LABEL[state]}
        style={size === "small" ? { width: "4rem", height: "4rem" } : undefined}
      />
      {size === "large" && (
        <p className="text-sm tracking-widest text-slate-400 uppercase" aria-live="polite">
          {LABEL[state]}
        </p>
      )}
    </div>
  );
}
