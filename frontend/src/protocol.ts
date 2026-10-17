// Spiegel von backend/src/cat/ws/protocol.py. Dokumentation: docs/protocol.md.

export type Role = "user" | "assistant" | "system";
export type Risk = "low" | "medium" | "high";
export type DeviceType =
  | "light"
  | "switch"
  | "dimmer"
  | "shutter"
  | "thermostat"
  | "sensor"
  | "lock"
  | "door"
  | "garage";
export type ControlMode = "readonly" | "test" | "full";

export interface DeviceInfo {
  id: string;
  name: string;
  room: string;
  type: DeviceType;
  risk: Risk;
  state: string | null;
  unit: string | null;
  online: boolean;
  controllable: boolean;
  test: boolean;
}

export type VoiceStateName = "idle" | "listening" | "thinking" | "speaking";
export type WidgetStatus = "loading" | "ok" | "error";

export interface ChartDataset {
  label: string;
  data: number[];
}

export interface ChartSpec {
  type: "bar" | "line" | "pie" | "doughnut";
  labels: string[];
  datasets: ChartDataset[];
  x_label?: string | null;
  y_label?: string | null;
}

export interface StageItem {
  id: string;
  kind: "html" | "chart" | "markdown" | "devices" | "image";
  title: string;
  content: string;
  chart: ChartSpec | null;
  created_at: number;
}

// --- Server -> Browser ---

export type ServerEvent =
  | { type: "chat.message"; id: string; role: Role; text: string; ts: number }
  | { type: "chat.delta"; id: string; delta: string }
  | { type: "chat.done"; id: string }
  | { type: "chat.clear" }
  | { type: "stage.show"; item: StageItem }
  | { type: "stage.clear" }
  | {
      type: "widget.update";
      id: string;
      kind: string;
      title: string;
      status: WidgetStatus;
      data: Record<string, unknown>;
      error: string | null;
      updated_at: number | null;
      refreshable: boolean;
    }
  | { type: "voice.state"; state: VoiceStateName }
  | { type: "device.list"; control: ControlMode; error: string | null; devices: DeviceInfo[] }
  | { type: "device.state"; id: string; state: string | null; unit: string | null; online: boolean }
  | {
      type: "confirm.request";
      id: string;
      device: string;
      command: string;
      summary: string;
      expires_in: number;
    }
  | { type: "confirm.resolved"; id: string }
  | { type: "provider.state"; name: string; offline: boolean }
  | { type: "error"; message: string };

// --- Browser -> Server ---

export type ClientEvent =
  | { type: "chat.message"; text: string }
  | { type: "chat.clear" }
  | { type: "stage.clear" }
  | { type: "widget.refresh"; id: string }
  | { type: "confirm.response"; id: string; approved: boolean }
  | { type: "device.command"; id: string; command: string };

const SERVER_TYPES = new Set<string>([
  "chat.message",
  "chat.delta",
  "chat.done",
  "chat.clear",
  "stage.show",
  "stage.clear",
  "widget.update",
  "voice.state",
  "device.list",
  "device.state",
  "confirm.request",
  "confirm.resolved",
  "provider.state",
  "error",
]);

/** Parst eine Servernachricht; unbekannte oder kaputte Nachrichten ergeben null. */
export function parseServerEvent(raw: string): ServerEvent | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "type" in value &&
      typeof value.type === "string" &&
      SERVER_TYPES.has(value.type)
    ) {
      return value as ServerEvent;
    }
  } catch {
    // ungültiges JSON
  }
  return null;
}
