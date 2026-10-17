import { useEffect, useState } from "react";
import type { WidgetState } from "../../state/store";
import { HudPanel as WidgetCard } from "../hud/Hud";
import { formatClock, formatNumber, num, weekday } from "./format";

interface Day {
  date: string;
  tmax: number | null;
  tmin: number | null;
  label: string;
}

function readDays(value: unknown): Day[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry): Day[] => {
    if (typeof entry !== "object" || entry === null) return [];
    const e = entry as Record<string, unknown>;
    if (typeof e.date !== "string") return [];
    return [{ date: e.date, tmax: num(e.tmax), tmin: num(e.tmin), label: typeof e.label === "string" ? e.label : "" }];
  });
}

export default function WeatherWidget({
  widget,
  onRefresh,
}: {
  widget: WidgetState;
  onRefresh: () => void;
}) {
  // Der Server antwortet auf jeden Refresh mit einem neuen widget.update (neuer Zeitstempel).
  const [waitingFor, setWaitingFor] = useState<number | null | undefined>(undefined);
  const pending = waitingFor !== undefined && widget.updatedAt === waitingFor;
  useEffect(() => {
    if (waitingFor === undefined) return;
    const t = setTimeout(() => setWaitingFor(undefined), 8000);
    return () => clearTimeout(t);
  }, [waitingFor]);

  const d = widget.data;
  const temp = num(d.temperature);
  const days = readDays(d.daily);
  const place = typeof d.name === "string" && d.name ? d.name : null;

  const refresh = (
    <button
      type="button"
      onClick={() => {
        setWaitingFor(widget.updatedAt);
        onRefresh();
      }}
      disabled={pending}
      aria-label="Wetter aktualisieren"
      className="hud-btn rounded-md px-2 py-0.5 text-xs disabled:opacity-50"
    >
      {pending ? "…" : "Aktualisieren"}
    </button>
  );

  return (
    <WidgetCard title={place ? `${widget.title} · ${place}` : widget.title} action={refresh}>
      {widget.status === "loading" && temp === null && <p className="text-sm text-cyan-200/40">Lade …</p>}
      {widget.status === "error" && (
        <p role="alert" className="mb-2 text-sm text-rose-400">
          {widget.error ?? "Wetter nicht verfügbar"}
          {temp !== null && widget.updatedAt !== null ? " Angezeigt ist der letzte bekannte Stand." : ""}
        </p>
      )}
      {temp !== null && (
        <div className={widget.status === "error" ? "opacity-60" : undefined}>
          <div className="flex items-baseline gap-2">
            <span className="hud-text-glow text-[clamp(1.8rem,5vh,3rem)] font-light tabular-nums text-cyan-50">{formatNumber(temp, 0)} °C</span>
            <span className="text-sm text-cyan-100/80">{typeof d.label === "string" ? d.label : ""}</span>
          </div>
          <p className="mt-1 text-xs text-cyan-200/60">
            Gefühlt {num(d.apparent) !== null ? `${formatNumber(num(d.apparent) ?? 0, 0)} °C` : "–"}
            {num(d.humidity) !== null ? ` · ${formatNumber(num(d.humidity) ?? 0)} % Luftfeuchte` : ""}
            {num(d.wind) !== null ? ` · Wind ${formatNumber(num(d.wind) ?? 0)} km/h` : ""}
          </p>
          {days.length > 0 && (
            <ul className="mt-3 grid gap-1 text-xs" aria-label="Vorhersage">
              {days.map((day) => (
                <li key={day.date} className="flex items-baseline justify-between gap-2">
                  <span className="w-8 text-cyan-200/60">{weekday(day.date)}</span>
                  <span className="min-w-0 flex-1 truncate text-cyan-100/80">{day.label}</span>
                  <span className="tabular-nums text-cyan-50">
                    {day.tmin !== null ? Math.round(day.tmin) : "–"}° / {day.tmax !== null ? Math.round(day.tmax) : "–"}°
                  </span>
                </li>
              ))}
            </ul>
          )}
          {widget.updatedAt !== null && widget.status === "ok" && (
            <p className="mt-2 text-[0.7rem] text-cyan-200/40">Stand {formatClock(widget.updatedAt)} Uhr</p>
          )}
        </div>
      )}
    </WidgetCard>
  );
}
