import type { ControlMode, DeviceInfo } from "../../protocol";

export function isOn(device: DeviceInfo): boolean {
  const s = (device.state ?? "").trim();
  if (s.toUpperCase() === "ON") return true;
  const n = Number(s);
  return s !== "" && Number.isFinite(n) && n > 0 && (device.type === "dimmer" || device.type === "shutter");
}

/** Lesbare Anzeige des Zustands. */
export function displayState(device: DeviceInfo): string {
  if (!device.online) return "offline";
  const s = device.state;
  if (s === null || s === "") return "unbekannt";
  const upper = s.toUpperCase();
  if (upper === "ON") return "an";
  if (upper === "OFF") return "aus";
  const words: Record<string, string> = {
    locked: "verriegelt",
    unlocked: "entriegelt",
    open: "offen",
    closed: "geschlossen",
    opening: "öffnet",
    closing: "schließt",
  };
  const word = words[s.toLowerCase()];
  if (word) return word;
  if (device.type === "shutter" && Number.isFinite(Number(s))) {
    const closed = Number(s);
    if (closed <= 0) return "offen";
    if (closed >= 100) return "zu";
    return `${Math.round(closed)} % zu`;
  }
  const unit = device.unit ?? (device.type === "dimmer" ? "%" : "");
  return unit ? `${s.replace(".", ",")} ${unit}` : s;
}

export function controlNote(mode: ControlMode): string | null {
  if (mode === "readonly") return "Steuern ist ausgeschaltet, Cat kann nur lesen.";
  if (mode === "test") return "Testmodus: nur als Testgerät markierte Geräte sind steuerbar.";
  return null;
}

export function groupByRoom(devices: DeviceInfo[], room: string): [string, DeviceInfo[]][] {
  const wanted = room.trim().toLowerCase();
  const rooms = new Map<string, DeviceInfo[]>();
  for (const d of devices) {
    if (wanted && d.room.toLowerCase() !== wanted) continue;
    rooms.set(d.room, [...(rooms.get(d.room) ?? []), d]);
  }
  return [...rooms.entries()].sort(([a], [b]) => a.localeCompare(b, "de"));
}

/** Schrittweite für Thermostat-Knöpfe, begrenzt auf den erlaubten Bereich 5 bis 30. */
export function nextSetpoint(device: DeviceInfo, delta: number): number | null {
  const current = Number(device.state);
  if (device.state === null || !Number.isFinite(current)) return null;
  return Math.min(30, Math.max(5, Math.round((current + delta) * 2) / 2));
}
