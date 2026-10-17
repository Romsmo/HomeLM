import { useNow } from "../hooks/useNow";
import type { ConnectionStatus } from "../lib/socket";
import type { WidgetState } from "../state/store";
import { weatherSummary } from "./widgets/weather";

const STATUS: Record<ConnectionStatus, { label: string; dot: string }> = {
  open: { label: "Online", dot: "bg-emerald-400" },
  connecting: { label: "Verbinde …", dot: "bg-amber-400 animate-pulse" },
  closed: { label: "Getrennt, verbinde neu …", dot: "bg-rose-500 animate-pulse" },
};

/** "anthropic/claude-haiku-5-5" -> "claude-haiku-5-5" */
function providerLabel(provider: { name: string; offline: boolean }): string {
  if (provider.offline) return "Offline-Modell";
  // Während einer Weitergabe an Claude zeigt der Hinweis, wer gerade antwortet.
  return provider.name.startsWith("claude/") ? "Claude antwortet" : "Modell";
}

export function shortModel(name: string): string {
  return name.includes("/") ? name.slice(name.indexOf("/") + 1) : name;
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
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-b border-cyan-400/20 bg-black/50 px-4 py-2 backdrop-blur">
      <div className="flex items-center gap-4">
        <h1 className="hud-text-glow text-xl font-semibold tracking-[0.3em] text-cyan-300 uppercase">Cat</h1>
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
                : "border-cyan-400/30 text-cyan-200/70"
            }`}
          >
            {providerLabel(provider)}: {shortModel(provider.name)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-5 text-sm">
        <span className="text-slate-300" data-testid="header-weather">
          {weatherSummary(weather)}
        </span>
        <div className="text-lg font-medium tabular-nums text-cyan-100">
          {now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="hud-btn rounded-lg px-3 py-1"
        >
          Abmelden
        </button>
      </div>
    </header>
  );
}
