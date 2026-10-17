/** Balken mit Beschriftung; ab 85 % gelb, ab 95 % rot. */
export default function Meter({
  label,
  percent,
  detail,
}: {
  label: string;
  percent: number | null;
  detail?: string;
}) {
  const value = percent === null ? 0 : Math.min(100, Math.max(0, percent));
  const color = value >= 95 ? "bg-rose-500" : value >= 85 ? "bg-amber-400" : "bg-cyan-300";
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
        <span className="tracking-wide text-cyan-100/80">{label}</span>
        <span className="tabular-nums text-cyan-200/60">
          {percent === null ? "–" : `${Math.round(value)} %`}
          {detail ? ` · ${detail}` : ""}
        </span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
        className="h-1.5 overflow-hidden bg-cyan-400/15"
      >
        <div
          className={`h-full transition-[width] duration-700 ${color}`}
          style={{ width: `${value}%`, boxShadow: "0 0 6px var(--hud-glow)" }}
        />
      </div>
    </div>
  );
}
