import type { ReactNode } from "react";

/** Glas-Fläche mit Eckklammern. Wächst mit dem verfügbaren Platz (flex) und scrollt notfalls innen. */
export function HudPanel({
  title,
  children,
  action,
  className = "",
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section aria-label={title} className={`hud-panel flex min-h-0 flex-col p-3 ${className}`}>
      <header className="mb-2 flex shrink-0 items-center justify-between gap-2">
        <h2 className="hud-title">{title}</h2>
        {action}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  );
}

function tone(value: number): string {
  if (value >= 95) return "#f43f5e";
  if (value >= 85) return "#fbbf24";
  return "#22e5ff";
}

const CIRCLE = 2 * Math.PI * 42;

/**
 * Ringanzeige (0 bis 100 %). Die Größe richtet sich nach der Breite des Behälters
 * (aspect-square, w-full), die Schrift skaliert mit.
 */
export function Ring({
  label,
  percent,
  display,
  detail,
  className = "",
}: {
  label: string;
  percent: number | null;
  /** Text in der Mitte, Standard: gerundeter Prozentwert. */
  display?: string;
  detail?: string;
  className?: string;
}) {
  const value = percent === null ? 0 : Math.min(100, Math.max(0, percent));
  const color = tone(value);
  return (
    <div className={`flex min-w-0 flex-col items-center gap-1 ${className}`}>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
        className="relative aspect-square w-full max-w-[9rem]"
      >
        <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden>
          <circle cx="50" cy="50" r="47" fill="none" stroke="var(--hud-faint)" strokeWidth="0.6" strokeDasharray="1.2 2.4" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--hud-faint)" strokeWidth="7" />
          <circle
            className="ring-arc"
            cx="50"
            cy="50"
            r="42"
            fill="none"
            stroke={color}
            strokeWidth="7"
            strokeLinecap="butt"
            strokeDasharray={`${(CIRCLE * value) / 100} ${CIRCLE}`}
            transform="rotate(-90 50 50)"
          />
          <circle cx="50" cy="50" r="33" fill="none" stroke="var(--hud-faint)" strokeWidth="0.8" />
        </svg>
        <div className="absolute inset-0 grid place-items-center text-center">
          <div className="leading-tight">
            <div className="hud-text-glow text-[clamp(0.9rem,2.4vh,1.5rem)] font-light tabular-nums text-cyan-100">
              {display ?? (percent === null ? "–" : `${Math.round(value)} %`)}
            </div>
            <div className="text-[0.62rem] tracking-widest text-cyan-300/70 uppercase">{label}</div>
          </div>
        </div>
      </div>
      {detail && <p className="text-center text-[0.68rem] text-cyan-200/60 tabular-nums">{detail}</p>}
    </div>
  );
}
