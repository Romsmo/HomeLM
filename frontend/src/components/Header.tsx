import { useEffect, useState } from "react";
import type { ConnectionStatus } from "../lib/socket";
import type { WidgetState } from "../state/store";
import { weatherSummary } from "./widgets/weather";

const STATUS: Record<ConnectionStatus, { label: string; dot: string }> = {
  open: { label: "Online", dot: "bg-emerald-400" },
  connecting: { label: "Verbinde …", dot: "bg-amber-400 animate-pulse" },
  closed: { label: "Getrennt, verbinde neu …", dot: "bg-rose-500 animate-pulse" },
};

/** "anthropic/claude-haiku-5-5" -> "claude-haiku-5-5" */
export function shortModel(name: string): string {
  return name.includes("/") ? name.slice(name.indexOf("/") + 1) : name;
}

function useNow(intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export default function Header({
  connection,
  weather,
  provider,
  onLogout,
}: {
  connection: ConnectionStatus;
  weather: WidgetState | undefined;
  provider?: { name: string; offline: boolean } | null;
  onLogout: () => void;
}) {
  const now = useNow();
  const status = STATUS[connection];
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-slate-800 bg-slate-900/60 px-4 py-3 backdrop-blur">
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-semibold tracking-[0.3em] text-cyan-300 uppercase">Cat</h1>
        <div className="flex items-center gap-2 text-sm text-slate-300" role="status">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${status.dot}`} aria-hidden />
          {status.label}
        </div>
        {provider && (
          <span
            data-testid="provider-badge"
            title={provider.name}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              provider.offline
                ? "border-amber-500/70 bg-amber-950/50 text-amber-300"
                : "border-slate-700 text-slate-400"
            }`}
          >
            {provider.offline ? "Offline-Modell" : "Modell"}: {shortModel(provider.name)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-5 text-sm">
        <span className="text-slate-300" data-testid="header-weather">
          {weatherSummary(weather)}
        </span>
        <div className="text-right leading-tight">
          <div className="text-lg font-medium tabular-nums">
            {now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </div>
          <div className="text-xs text-slate-400">
            {now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" })}
          </div>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-300 transition hover:border-slate-500 hover:text-white"
        >
          Abmelden
        </button>
      </div>
    </header>
  );
}
