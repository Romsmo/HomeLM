import { useNow } from "../../hooks/useNow";

const CIRCLE = 2 * Math.PI * 44;

/** Datum im Ring (große Tageszahl, Monat, Wochentag); der Bogen zeigt den Tagesfortschritt. */
export function DateRing() {
  const now = useNow(30_000);
  const dayProgress = (now.getHours() * 60 + now.getMinutes()) / 1440;
  return (
    <div className="flex h-full w-full items-center justify-center">
    <div
      className="@container relative aspect-square h-full max-h-full max-w-full [container-type:size]"
      role="img"
      aria-label={now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
    >
      <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden>
        <circle cx="50" cy="50" r="48" fill="none" stroke="var(--hud-faint)" strokeWidth="0.6" strokeDasharray="1.2 2.4" />
        <circle cx="50" cy="50" r="44" fill="none" stroke="var(--hud-faint)" strokeWidth="3" />
        <circle
          className="ring-arc"
          cx="50"
          cy="50"
          r="44"
          fill="none"
          stroke="var(--hud)"
          strokeWidth="3"
          strokeDasharray={`${CIRCLE * dayProgress} ${CIRCLE}`}
          transform="rotate(-90 50 50)"
        />
        <path d="M30 70 A 28 28 0 0 0 70 70" fill="none" stroke="var(--hud)" strokeWidth="1.2" opacity="0.7" />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div className="leading-none">
          <div className="text-[0.7rem] tracking-[0.25em] text-cyan-300/80 uppercase">
            {now.toLocaleDateString("de-DE", { month: "long" })}
          </div>
          <div className="hud-text-glow my-1 text-[clamp(1.6rem,12cqmin,3.6rem)] font-light tabular-nums text-cyan-50">
            {now.getDate()}
          </div>
          <div className="text-[0.7rem] tracking-[0.2em] text-cyan-300/70 uppercase">
            {now.toLocaleDateString("de-DE", { weekday: "long" })}
          </div>
        </div>
      </div>
    </div>
    </div>
  );
}

/** Uhrzeit im Ring; der Bogen läuft mit den Sekunden. */
export function ClockRing() {
  const now = useNow(1000);
  const seconds = now.getSeconds() + now.getMilliseconds() / 1000;
  return (
    <div className="flex h-full w-full items-center justify-center">
    <div
      className="@container relative aspect-square h-full max-h-full max-w-full [container-type:size]"
      role="img"
      aria-label={now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
    >
      <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden>
        <circle cx="50" cy="50" r="46" fill="none" stroke="var(--hud-faint)" strokeWidth="1" />
        <circle cx="50" cy="50" r="40" fill="none" stroke="var(--hud-faint)" strokeWidth="6" />
        <circle
          cx="50"
          cy="50"
          r="40"
          fill="none"
          stroke="var(--hud)"
          strokeWidth="6"
          strokeDasharray={`${(2 * Math.PI * 40 * seconds) / 60} ${2 * Math.PI * 40}`}
          transform="rotate(-90 50 50)"
          style={{ filter: "drop-shadow(0 0 3px var(--hud-glow))" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="hud-text-glow text-[clamp(1rem,16cqmin,1.9rem)] font-light tabular-nums text-cyan-50">
          {now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </div>
    </div>
  );
}
