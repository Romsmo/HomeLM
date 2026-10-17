import type { WidgetState } from "../../state/store";
import { HudPanel as WidgetCard, Ring } from "../hud/Hud";
import { formatBytes, formatNumber, num } from "./format";
import Meter from "./Meter";

export default function SystemWidget({ widget }: { widget: WidgetState }) {
  const d = widget.data;
  const load = Array.isArray(d.load) ? d.load.filter((x): x is number => typeof x === "number") : [];
  const memUsed = num(d.mem_used);
  const memTotal = num(d.mem_total);
  const diskUsed = num(d.disk_used);
  const diskTotal = num(d.disk_total);
  const hasData = num(d.cpu_percent) !== null;

  return (
    <WidgetCard title={widget.title}>
      {widget.status === "loading" && !hasData && <p className="text-sm text-cyan-200/50">Lade …</p>}
      {widget.status === "error" && (
        <p role="alert" className="text-sm text-rose-400">
          {widget.error ?? "Nicht verfügbar"}
        </p>
      )}
      {hasData && widget.status === "ok" && (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Ring
              label="CPU"
              percent={num(d.cpu_percent)}
              detail={num(d.cpu_count) ? `${num(d.cpu_count)} Kerne` : undefined}
            />
            <Ring
              label="Arbeitsspeicher"
              percent={num(d.mem_percent)}
              detail={
                memUsed !== null && memTotal !== null
                  ? `${formatBytes(memUsed)} / ${formatBytes(memTotal)}`
                  : undefined
              }
            />
          </div>
          <Meter
            label="Datenträger"
            percent={num(d.disk_percent)}
            detail={
              diskUsed !== null && diskTotal !== null
                ? `${formatBytes(diskUsed)} / ${formatBytes(diskTotal)}`
                : undefined
            }
          />
          {load.length === 3 && (
            <p className="text-xs text-cyan-200/50">Last {load.map((x) => formatNumber(x, 2)).join(" · ")}</p>
          )}
        </div>
      )}
    </WidgetCard>
  );
}
