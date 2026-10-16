import type { ReactNode } from "react";
import type { WidgetState } from "../../state/store";
import { WidgetCard } from "../WidgetColumn";
import SystemWidget from "./SystemWidget";
import UptimeWidget from "./UptimeWidget";
import WeatherWidget from "./WeatherWidget";

/** Wählt die Darstellung nach `kind`; unbekannte Arten zeigen Status und Fehler. */
export function renderWidget(widget: WidgetState, onRefresh: (id: string) => void): ReactNode {
  switch (widget.kind) {
    case "system":
      return <SystemWidget widget={widget} />;
    case "uptime":
      return <UptimeWidget widget={widget} />;
    case "weather":
      return <WeatherWidget widget={widget} onRefresh={() => onRefresh(widget.id)} />;
    default:
      return (
        <WidgetCard title={widget.title}>
          <p className={widget.status === "error" ? "text-sm text-rose-400" : "text-sm text-slate-400"}>
            {widget.status === "error" ? (widget.error ?? "Fehler") : widget.status === "loading" ? "Lade …" : "OK"}
          </p>
        </WidgetCard>
      );
  }
}
