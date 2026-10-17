import type { ControlMode, DeviceInfo } from "../../protocol";
import { WidgetCard } from "../WidgetColumn";

const MODE_LABEL: Record<ControlMode, string> = {
  readonly: "nur lesen",
  test: "Testmodus",
  full: "Steuern aktiv",
};

export default function DevicesCard({
  devices,
  control,
  onOpen,
}: {
  devices: DeviceInfo[];
  control: ControlMode;
  onOpen: () => void;
}) {
  const offline = devices.filter((d) => !d.online).length;
  return (
    <div className="mt-3">
      <WidgetCard
        title="Geräte"
        action={
          <button
            type="button"
            onClick={onOpen}
            className="rounded-md border border-slate-700 px-2 py-0.5 text-xs text-slate-300 transition hover:border-slate-500"
          >
            Panel öffnen
          </button>
        }
      >
        {devices.length === 0 ? (
          <p className="text-sm text-slate-500">Keine Geräte freigegeben.</p>
        ) : (
          <p className="text-sm text-slate-300">
            {devices.length} Geräte{offline > 0 ? `, ${offline} offline` : ""} · {MODE_LABEL[control]}
          </p>
        )}
      </WidgetCard>
    </div>
  );
}
