import { type ClientEvent, type ServerEvent, parseServerEvent } from "../protocol";

export type ConnectionStatus = "connecting" | "open" | "closed";

export interface SocketOptions {
  url: string;
  onEvent: (event: ServerEvent) => void;
  onStatus: (status: ConnectionStatus) => void;
  /** Verbindung kam nie zustande (z. B. Sitzung abgelaufen): Aufrufer kann die Anmeldung prüfen. */
  onUnreachable?: () => void;
  /** Wartezeit vor dem n-ten Wiederverbindungsversuch (ab 0). */
  backoffMs?: (attempt: number) => number;
  createSocket?: (url: string) => WebSocket;
}

const defaultBackoff = (attempt: number): number => Math.min(1000 * 2 ** attempt, 15000);

/** WebSocket mit automatischer Wiederverbindung (exponentiell, max. 15 s). */
export class ReconnectingSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private openedOnce = false;

  constructor(private readonly opts: SocketOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.ws?.close();
    this.ws = null;
  }

  send(event: ClientEvent): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(event));
    return true;
  }

  private connect(): void {
    this.openedOnce = false;
    this.opts.onStatus("connecting");
    const ws = (this.opts.createSocket ?? ((u) => new WebSocket(u)))(this.opts.url);
    this.ws = ws;
    ws.onopen = () => {
      this.openedOnce = true;
      this.attempt = 0;
      this.opts.onStatus("open");
    };
    ws.onmessage = (msg: MessageEvent) => {
      if (typeof msg.data !== "string") return;
      const event = parseServerEvent(msg.data);
      if (event) this.opts.onEvent(event);
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.opts.onStatus("closed");
      if (this.stopped) return;
      if (!this.openedOnce) this.opts.onUnreachable?.();
      const delay = (this.opts.backoffMs ?? defaultBackoff)(this.attempt++);
      this.timer = setTimeout(() => {
        this.timer = null;
        if (!this.stopped) this.connect();
      }, delay);
    };
  }
}
