import type { ConnectionStatus } from "../lib/socket";
import type {
  ControlMode,
  DeviceInfo,
  Role,
  ServerEvent,
  StageItem,
  VoiceStateName,
} from "../protocol";

export interface ChatItem {
  id: string;
  role: Role;
  text: string;
  ts: number;
  streaming: boolean;
}

export interface WidgetState {
  id: string;
  kind: string;
  title: string;
  status: "loading" | "ok" | "error";
  data: Record<string, unknown>;
  error: string | null;
  updatedAt: number | null;
  refreshable: boolean;
}

export interface PendingConfirm {
  id: string;
  device: string;
  command: string;
  summary: string;
  expiresIn: number;
  receivedAt: number;
}

export interface CatState {
  connection: ConnectionStatus;
  messages: ChatItem[];
  voice: VoiceStateName;
  stage: StageItem[];
  stageIndex: number;
  widgets: Record<string, WidgetState>;
  devices: DeviceInfo[];
  control: ControlMode;
  deviceError: string | null;
  confirm: PendingConfirm | null;
  provider: { name: string; offline: boolean } | null;
  notice: string | null;
}

export type Action =
  | { kind: "server"; event: ServerEvent }
  | { kind: "connection"; status: ConnectionStatus }
  | { kind: "stageGo"; index: number }
  | { kind: "dismissNotice" }
  | { kind: "confirmClose" }
  | { kind: "showDevices" };

export const initialState: CatState = {
  connection: "connecting",
  messages: [],
  voice: "idle",
  stage: [],
  stageIndex: -1,
  widgets: {},
  devices: [],
  control: "readonly",
  deviceError: null,
  confirm: null,
  provider: null,
  notice: null,
};

function applyServerEvent(state: CatState, event: ServerEvent): CatState {
  switch (event.type) {
    case "chat.message": {
      const item: ChatItem = {
        id: event.id,
        role: event.role,
        text: event.text,
        ts: event.ts,
        // Leere Assistentennachricht = Antwort läuft, Text kommt per chat.delta.
        streaming: event.role === "assistant" && event.text === "",
      };
      const exists = state.messages.some((m) => m.id === event.id);
      return {
        ...state,
        messages: exists
          ? state.messages.map((m) => (m.id === event.id ? item : m))
          : [...state.messages, item],
      };
    }
    case "chat.delta":
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === event.id ? { ...m, text: m.text + event.delta } : m,
        ),
      };
    case "chat.done":
      return {
        ...state,
        messages: state.messages
          // Eine Antwort ohne Text (Fehler) verschwindet wieder.
          .filter((m) => !(m.id === event.id && m.text === ""))
          .map((m) => (m.id === event.id ? { ...m, streaming: false } : m)),
      };
    case "chat.clear":
      return { ...state, messages: [] };
    case "stage.show": {
      if (state.stage.some((s) => s.id === event.item.id)) return state;
      const stage = [...state.stage, event.item];
      return { ...state, stage, stageIndex: stage.length - 1 };
    }
    case "stage.clear":
      return { ...state, stage: [], stageIndex: -1 };
    case "widget.update":
      return {
        ...state,
        widgets: {
          ...state.widgets,
          [event.id]: {
            id: event.id,
            kind: event.kind,
            title: event.title,
            status: event.status,
            data: event.data,
            error: event.error,
            updatedAt: event.updated_at,
            refreshable: event.refreshable,
          },
        },
      };
    case "voice.state":
      return { ...state, voice: event.state };
    case "device.list":
      return { ...state, devices: event.devices, control: event.control, deviceError: event.error };
    case "device.state":
      return {
        ...state,
        devices: state.devices.map((d) =>
          d.id === event.id ? { ...d, state: event.state, unit: event.unit, online: event.online } : d,
        ),
      };
    case "confirm.request":
      return {
        ...state,
        confirm: {
          id: event.id,
          device: event.device,
          command: event.command,
          summary: event.summary,
          expiresIn: event.expires_in,
          receivedAt: Date.now(),
        },
      };
    case "provider.state":
      return { ...state, provider: { name: event.name, offline: event.offline } };
    case "confirm.resolved":
      return state.confirm?.id === event.id ? { ...state, confirm: null } : state;
    case "error":
      return { ...state, notice: event.message };
  }
}

export function reducer(state: CatState, action: Action): CatState {
  switch (action.kind) {
    case "server":
      return applyServerEvent(state, action.event);
    case "connection":
      // Nach (Wieder-)Verbindung schickt der Server alles erneut: lokalen Stand verwerfen.
      return action.status === "open"
        ? { ...initialState, connection: "open" }
        : { ...state, connection: action.status, voice: action.status === "closed" ? "idle" : state.voice };
    case "stageGo":
      return {
        ...state,
        stageIndex: Math.max(0, Math.min(action.index, state.stage.length - 1)),
      };
    case "dismissNotice":
      return { ...state, notice: null };
    case "confirmClose":
      return { ...state, confirm: null };
    case "showDevices": {
      // Lokal geöffnetes Panel (ohne Server): zeigt immer den aktuellen Gerätestand.
      const item: StageItem = {
        id: `local-devices-${state.stage.length}`,
        kind: "devices",
        title: "Geräte",
        content: "",
        chart: null,
        created_at: Date.now() / 1000,
      };
      const stage = [...state.stage, item];
      return { ...state, stage, stageIndex: stage.length - 1 };
    }
  }
}
