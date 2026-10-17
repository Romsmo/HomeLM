import type { WidgetState } from "../../state/store";
import { HudPanel as WidgetCard } from "../hud/Hud";
import { formatDuration, num } from "./format";

export default function UptimeWidget({ widget }: { widget: WidgetState }) {
  const system = num(widget.data.system_seconds);
  const cat = num(widget.data.cat_seconds);
  return (
    <WidgetCard title={widget.title}>
      {widget.status === "error" && (
        <p role="alert" className="text-sm text-rose-400">
          {widget.error ?? "Nicht verfügbar"}
        </p>
      )}
      {widget.status === "loading" && system === null && <p className="text-sm text-cyan-200/50">Lade …</p>}
      {system !== null && widget.status === "ok" && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-cyan-300/70">Server</dt>
          <dd className="text-right tabular-nums">{formatDuration(system)}</dd>
          <dt className="text-cyan-300/70">Cat</dt>
          <dd className="text-right tabular-nums">{cat !== null ? formatDuration(cat) : "–"}</dd>
        </dl>
      )}
    </WidgetCard>
  );
}
