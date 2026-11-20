import type { MicControl } from "../../hooks/useVoice";

const LABEL: Record<MicControl["state"], string> = {
  off: "Mikrofon aus",
  connecting: "Mikrofon verbindet",
  ready: "Wartet auf Sprache",
  listening: "Hört zu",
  thinking: "Denkt nach",
  speaking: "Spricht",
};

/** Kleiner Leuchtpunkt, der zeigt, was Cat gerade tut (siehe `.orb` in hud.css). */
export default function VoiceOrb({ mode, large = false }: { mode: MicControl["state"]; large?: boolean }) {
  return (
    <span
      role="img"
      aria-label={LABEL[mode]}
      data-mode={mode}
      className={`orb orb-${mode} ${large ? "orb-large" : ""}`}
    />
  );
}
