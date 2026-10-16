import type { ReactNode } from "react";
import type { WidgetState } from "../state/store";

/** Reihenfolge und Platzhalter, solange ein Widget noch keine Daten geliefert hat. */
const SLOTS = [
  { id: "system", title: "System" },
  { id: "weather", title: "Wetter" },
  { id: "uptime", title: "Uptime" },
] as const;

export function WidgetCard({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur"
    >
      <header className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-semibold tracking-widest text-slate-400 uppercase">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export default function WidgetColumn({
  widgets,
  renderWidget,
}: {
  widgets: Record<string, WidgetState>;
  renderWidget: (widget: WidgetState) => ReactNode;
}) {
  return (
    <aside
      aria-label="Widgets"
      className="grid grid-cols-1 gap-3 sm:grid-cols-3 xl:grid-cols-1 xl:content-start xl:overflow-y-auto"
    >
      {SLOTS.map(({ id, title }) => {
        const widget = widgets[id];
        return widget ? (
          <div key={id}>{renderWidget(widget)}</div>
        ) : (
          <WidgetCard key={id} title={title}>
            <p className="text-sm text-slate-500">Warte auf Daten …</p>
          </WidgetCard>
        );
      })}
    </aside>
  );
}
