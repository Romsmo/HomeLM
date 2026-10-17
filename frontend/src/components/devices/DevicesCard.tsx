import type { ControlMode, DeviceInfo } from "../../protocol";
import { HudPanel } from "../hud/Hud";
import { displayState, isOn } from "./deviceUtils";

const MODE_LABEL: Record<ControlMode, string> = {
  readonly: "nur lesen",
  test: "Testmodus",
  full: "Steuern aktiv",
};

/** Geräte-Widget: Überblick über alle freigegebenen Geräte, das Panel öffnet sich auf der Stage. */
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
    <HudPanel
      title="Geräte"
      className="min-h-[7rem]"
      action={
        <button type="button" onClick={onOpen} className="hud-btn rounded-md px-2 py-0.5 text-xs">
          Panel öffnen
        </button>
      }
    >
      {devices.length === 0 ? (
        <p className="text-sm text-cyan-200/50">Keine Geräte freigegeben.</p>
      ) : (
        <>
          <p className="mb-2 text-xs text-cyan-200/60">
            {devices.length} Geräte{offline > 0 ? `, ${offline} offline` : ""} · {MODE_LABEL[control]}
          </p>
          <ul className="grid gap-1 text-sm" aria-label="Geräteübersicht">
            {devices.map((d) => (
              <li key={d.id} className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    !d.online ? "bg-rose-500" : isOn(d) ? "bg-cyan-300 shadow-[0_0_6px_var(--hud)]" : "bg-cyan-900"
                  }`}
                />
                <span className="min-w-0 flex-1 truncate text-cyan-100/90">{d.name}</span>
                <span className="shrink-0 text-xs tabular-nums text-cyan-200/60">{displayState(d)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </HudPanel>
  );
}
