import type { ServerEvent } from "../protocol";
import { type ConnectionStatus, ReconnectingSocket } from "./socket";

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
  emit(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent);
  }
}

function setup(extra: { onUnreachable?: () => void } = {}) {
  FakeSocket.instances = [];
  const events: ServerEvent[] = [];
  const statuses: ConnectionStatus[] = [];
  const socket = new ReconnectingSocket({
    url: "ws://test/ws",
    onEvent: (e) => events.push(e),
    onStatus: (s) => statuses.push(s),
    backoffMs: () => 1000,
    createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
    ...extra,
  });
  return { socket, events, statuses };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", Object.assign(FakeSocket, { OPEN: 1 }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ReconnectingSocket", () => {
  it("verbindet sich nach einem Abbruch automatisch neu", () => {
    const { socket, statuses } = setup();
    socket.start();
    FakeSocket.instances[0]?.open();
    FakeSocket.instances[0]?.drop();
    expect(statuses).toEqual(["connecting", "open", "closed"]);
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1]?.open();
    expect(statuses.at(-1)).toBe("open");
  });

  it("meldet 'unerreichbar', wenn die Verbindung nie zustande kam", () => {
    const onUnreachable = vi.fn();
    const { socket } = setup({ onUnreachable });
    socket.start();
    FakeSocket.instances[0]?.drop();
    expect(onUnreachable).toHaveBeenCalledTimes(1);
  });

  it("meldet nichts bei Abbruch nach erfolgreicher Verbindung", () => {
    const onUnreachable = vi.fn();
    const { socket } = setup({ onUnreachable });
    socket.start();
    FakeSocket.instances[0]?.open();
    FakeSocket.instances[0]?.drop();
    expect(onUnreachable).not.toHaveBeenCalled();
  });

  it("leitet gültige Events weiter und ignoriert kaputte", () => {
    const { socket, events } = setup();
    socket.start();
    const ws = FakeSocket.instances[0];
    ws?.open();
    ws?.emit({ type: "voice.state", state: "thinking" });
    ws?.emit("kein json");
    ws?.emit({ type: "unbekannt" });
    expect(events).toEqual([{ type: "voice.state", state: "thinking" }]);
  });

  it("sendet nur auf offener Verbindung", () => {
    const { socket } = setup();
    socket.start();
    expect(socket.send({ type: "chat.clear" })).toBe(false);
    FakeSocket.instances[0]?.open();
    expect(socket.send({ type: "chat.message", text: "hi" })).toBe(true);
    expect(FakeSocket.instances[0]?.sent).toEqual([JSON.stringify({ type: "chat.message", text: "hi" })]);
  });

  it("verbindet nach stop() nicht mehr neu", () => {
    const { socket } = setup();
    socket.start();
    FakeSocket.instances[0]?.open();
    socket.stop();
    vi.advanceTimersByTime(60000);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
