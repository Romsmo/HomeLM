import type { WidgetState } from "../../state/store";

/** Kurztext fürs Header-Feld: "12 °C, Leicht bewölkt" oder ein Platzhalter. */
export function weatherSummary(widget: WidgetState | undefined): string {
  if (!widget || widget.status === "loading") return "Wetter: …";
  if (widget.status === "error") return "Wetter: nicht verfügbar";
  const temp = widget.data.temperature;
  const label = widget.data.label;
  if (typeof temp !== "number") return "Wetter: –";
  const text = typeof label === "string" ? `, ${label}` : "";
  return `${Math.round(temp)} °C${text}`;
}
