import { useState } from "react";
import type { ControlMode, DeviceInfo } from "../../protocol";
import { controlNote, displayState, groupByRoom, isOn, nextSetpoint } from "./deviceUtils";

const TYPE_LABEL: Record<DeviceInfo["type"], string> = {
  light: "Licht",
  switch: "Schalter",
  dimmer: "Dimmer",
  shutter: "Rollladen",
  thermostat: "Thermostat",
  sensor: "Sensor",
  lock: "Schloss",
  door: "Tür",
  garage: "Garage",
};

const btn =
  "rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 transition hover:border-cyan-500 disabled:opacity-40";

type Send = (command: string) => void;

function Toggle({ device, onCommand }: { device: DeviceInfo; onCommand: Send }) {
  const on = isOn(device);
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`${device.name} ${on ? "ausschalten" : "einschalten"}`}
      onClick={() => onCommand(on ? "off" : "on")}
      className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "bg-cyan-500" : "bg-slate-700"}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${on ? "left-[1.375rem]" : "left-0.5"}`}
      />
    </button>
  );
}

function DimmerSlider({ device, onCommand }: { device: DeviceInfo; onCommand: Send }) {
  const current = Number(device.state);
  const [draft, setDraft] = useState<number | null>(null);
  const value = draft ?? (device.state !== null && Number.isFinite(current) ? current : 0);
  const commit = () => {
    if (draft !== null) onCommand(String(Math.round(draft)));
    setDraft(null);
  };
  return (
    <input
      type="range"
      min={0}
      max={100}
      step={5}
      value={value}
      aria-label={`${device.name} Helligkeit`}
      onChange={(e) => setDraft(Number(e.target.value))}
      onPointerUp={commit}
      onKeyUp={commit}
      className="w-24 accent-cyan-400"
    />
  );
}

function Controls({ device, onCommand }: { device: DeviceInfo; onCommand: Send }) {
  switch (device.type) {
    case "light":
    case "switch":
      return <Toggle device={device} onCommand={onCommand} />;
    case "dimmer":
      return (
        <div className="flex items-center gap-3">
          <DimmerSlider device={device} onCommand={onCommand} />
          <Toggle device={device} onCommand={onCommand} />
        </div>
      );
    case "shutter":
      return (
        <div className="flex gap-1.5">
          <button type="button" className={btn} onClick={() => onCommand("up")} aria-label={`${device.name} hoch`}>
            Hoch
          </button>
          <button type="button" className={btn} onClick={() => onCommand("stop")} aria-label={`${device.name} stopp`}>
            Stopp
          </button>
          <button type="button" className={btn} onClick={() => onCommand("down")} aria-label={`${device.name} runter`}>
            Runter
          </button>
        </div>
      );
    case "thermostat": {
      const down = nextSetpoint(device, -0.5);
      const up = nextSetpoint(device, 0.5);
      return (
        <div className="flex gap-1.5">
          <button
            type="button"
            className={btn}
            disabled={down === null}
            onClick={() => down !== null && onCommand(String(down))}
            aria-label={`${device.name} kälter`}
          >
            −
          </button>
          <button
            type="button"
            className={btn}
            disabled={up === null}
            onClick={() => up !== null && onCommand(String(up))}
            aria-label={`${device.name} wärmer`}
          >
            +
          </button>
        </div>
      );
    }
    case "lock":
      return (
        <div className="flex gap-1.5">
          <button type="button" className={btn} onClick={() => onCommand("lock")}>
            Verriegeln
          </button>
          <button type="button" className={btn} onClick={() => onCommand("unlock")}>
            Entriegeln
          </button>
        </div>
      );
    case "door":
    case "garage":
      return (
        <div className="flex gap-1.5">
          <button type="button" className={btn} onClick={() => onCommand("open")}>
            Öffnen
          </button>
          <button type="button" className={btn} onClick={() => onCommand("close")}>
            Schließen
          </button>
        </div>
      );
    default:
      return null;
  }
}

export default function DevicePanel({
  devices,
  control,
  error,
  room,
  onCommand,
}: {
  devices: DeviceInfo[];
  control: ControlMode;
  error: string | null;
  room: string;
  onCommand: (id: string, command: string) => void;
}) {
  const groups = groupByRoom(devices, room);
  const note = controlNote(control);
  return (
    <div className="h-full overflow-y-auto p-4 text-sm">
      {error && (
        <p role="alert" className="mb-3 rounded-lg bg-rose-950/60 px-3 py-2 text-rose-200">
          {error}
        </p>
      )}
      {note && <p className="mb-3 rounded-lg bg-slate-800/70 px-3 py-2 text-slate-300">{note}</p>}
      {groups.length === 0 && (
        <p className="text-slate-400">
          {devices.length === 0
            ? "Es sind keine Geräte freigegeben. Trage sie in data/config/devices.yaml ein."
            : `Im Raum „${room}“ gibt es keine freigegebenen Geräte.`}
        </p>
      )}
      {groups.map(([name, list]) => (
        <section key={name} aria-label={name} className="mb-4">
          <h3 className="mb-2 text-xs font-semibold tracking-widest text-slate-400 uppercase">{name}</h3>
          <ul className="grid gap-2">
            {list.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium text-slate-100">{d.name}</div>
                  <div className="text-xs text-slate-400">
                    {TYPE_LABEL[d.type]} · <span data-testid={`state-${d.id}`}>{displayState(d)}</span>
                    {d.risk === "high" && <span className="ml-2 text-amber-400">Bestätigung nötig</span>}
                    {d.test && <span className="ml-2 text-cyan-400">Test</span>}
                  </div>
                </div>
                {d.controllable && d.online ? (
                  <Controls device={d} onCommand={(c) => onCommand(d.id, c)} />
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
