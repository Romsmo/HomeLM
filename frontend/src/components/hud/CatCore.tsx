import { useId } from "react";
import type { VoiceStateName } from "../../protocol";

const LABEL: Record<VoiceStateName, string> = {
  idle: "Cat wartet",
  listening: "Cat hört zu",
  thinking: "Cat denkt nach",
  speaking: "Cat spricht",
};

/** Ein Ring aus Strichen (dash) oder Bögen, der sich dreht. */
function Rot({
  r,
  width,
  dash,
  dur,
  reverse,
  color = "var(--hud)",
  opacity = 1,
}: {
  r: number;
  width: number;
  dash: string;
  dur: number;
  reverse?: boolean;
  color?: string;
  opacity?: number;
}) {
  return (
    <g className={`core-rot${reverse ? " rev" : ""}`} style={{ ["--dur" as string]: `${dur}s` }}>
      <circle cx="200" cy="200" r={r} fill="none" stroke={color} strokeWidth={width} strokeDasharray={dash} opacity={opacity} />
    </g>
  );
}

/**
 * Das Gesicht von Cat: Ringe, Skala und ein leuchtender Kern, der Zuhören, Denken und Sprechen zeigt.
 * Ein Klick auf den Kern öffnet den Chat.
 */
export default function CatCore({
  state,
  onOpen,
}: {
  state: VoiceStateName;
  /** Ohne Funktion ist der Kern nur Anzeige (z. B. auf der Anmeldeseite). */
  onOpen?: () => void;
}) {
  const uid = useId().replace(/:/g, "");
  return (
    <div className="core relative aspect-square h-full max-h-full max-w-full" data-state={state}>
      <svg viewBox="0 0 400 400" className="h-full w-full" role="img" aria-label={LABEL[state]}>
        <defs>
          <radialGradient id={`orb-${uid}`} cx="38%" cy="32%" r="75%">
            <stop offset="0%" stopColor="var(--orb-a)" />
            <stop offset="38%" stopColor="var(--orb-b)" />
            <stop offset="78%" stopColor="var(--orb-c)" />
            <stop offset="100%" stopColor="#02202c" />
          </radialGradient>
          <radialGradient id={`halo-${uid}`} cx="50%" cy="50%" r="50%">
            <stop offset="55%" stopColor="var(--orb-glow)" stopOpacity="0.5" />
            <stop offset="100%" stopColor="var(--orb-glow)" stopOpacity="0" />
          </radialGradient>
        </defs>

        <circle cx="200" cy="200" r="198" fill={`url(#halo-${uid})`} opacity="0.35" />
        <circle cx="200" cy="200" r="194" fill="none" stroke="var(--hud-faint)" strokeWidth="1" />

        {/* Skala */}
        <Rot r={182} width={9} dash="1.4 8.1" dur={90} opacity={0.75} />
        <Rot r={170} width={2} dash="3 5" dur={70} reverse opacity={0.45} />

        {/* Kräftige Bögen */}
        <Rot r={152} width={12} dash="170 36 90 28 210 40 120 60" dur={46} opacity={0.85} />
        <Rot r={152} width={3} dash="4 940" dur={30} color="#f43f5e" />
        <Rot r={128} width={3} dash="40 12 8 12 120 20" dur={34} reverse opacity={0.8} />
        <Rot r={108} width={16} dash="240 24 150 40" dur={58} reverse opacity={0.38} />

        {/* Wellen bei Zuhören und Sprechen */}
        <circle className="core-ripple" cx="200" cy="200" r="150" fill="none" stroke="var(--orb-b)" strokeWidth="3" />
        <circle className="core-ripple b" cx="200" cy="200" r="150" fill="none" stroke="var(--orb-b)" strokeWidth="3" />

        {/* Kern */}
        <g className="core-orb">
          <circle cx="200" cy="200" r="86" fill="none" stroke="var(--orb-b)" strokeWidth="2" opacity="0.7" />
          <circle cx="200" cy="200" r="76" fill={`url(#orb-${uid})`} />
          <circle cx="200" cy="200" r="52" fill="none" stroke="var(--orb-a)" strokeWidth="1.5" opacity="0.5" />
          <ellipse cx="176" cy="172" rx="22" ry="12" fill="#fff" opacity="0.35" transform="rotate(-30 176 172)" />
        </g>
      </svg>
      {onOpen && (
        <button
          type="button"
          onClick={onOpen}
          aria-label="Chat öffnen"
          title="Chat öffnen"
          className="core-hit absolute top-1/2 left-1/2 aspect-square w-[44%] -translate-x-1/2 -translate-y-1/2 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        />
      )}
    </div>
  );
}

export { LABEL as CORE_LABEL };
