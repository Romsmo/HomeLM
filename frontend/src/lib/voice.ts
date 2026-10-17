/** Browser-Mikrofon und Wiedergabe für /ws/voice. Protokoll: docs/voice-protocol.md. */

export const TARGET_RATE = 16000;
export const FRAME_SAMPLES = 512; // 32 ms bei 16 kHz, so groß ist ein Fenster des Silero-VAD

export type MicState = "off" | "connecting" | "ready" | "listening" | "thinking" | "speaking";

export type VoiceEvent =
  | { type: "voice.ready"; stt: string }
  | { type: "voice.state"; state: "idle" | "listening" | "thinking" | "speaking" }
  | { type: "voice.transcript"; text: string }
  | { type: "voice.reply"; text: string }
  | { type: "voice.empty" }
  | { type: "voice.timeout" }
  | { type: "tts.start"; rate: number; channels: number; format: string }
  | { type: "tts.end"; expects_reply: boolean }
  | {
      type: "voice.latency";
      pause_ms: number;
      stt_ms: number;
      first_token_ms: number | null;
      first_audio_ms: number | null;
      total_ms: number;
      via_fastpath: boolean;
    }
  | { type: "error"; message: string };

const TYPES = new Set([
  "voice.ready", "voice.state", "voice.transcript", "voice.reply", "voice.empty",
  "voice.timeout", "tts.start", "tts.end", "voice.latency", "error",
]); // prettier-ignore

export function parseVoiceEvent(raw: string): VoiceEvent | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === "object" && value !== null && "type" in value && typeof value.type === "string" && TYPES.has(value.type)) {
      return value as VoiceEvent;
    }
  } catch {
    // ungültiges JSON
  }
  return null;
}

/** Float (-1..1) -> PCM16 little endian, begrenzt statt umzubrechen. */
export function floatToPcm16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i] ?? 0));
    out[i] = s < 0 ? s * 32768 : s * 32767;
  }
  return out;
}

export function pcm16ToFloat(pcm: Int16Array): Float32Array {
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = (pcm[i] ?? 0) / 32768;
  return out;
}

/** Mittelnde Dezimierung auf 16 kHz (reicht für Sprache). Gibt auch den Rest für den nächsten Block zurück. */
export function downsample(input: Float32Array, sourceRate: number): Float32Array {
  if (sourceRate === TARGET_RATE) return input;
  const ratio = sourceRate / TARGET_RATE;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j] ?? 0;
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

/** AudioWorklet-Code als Text (kein Bundler-Sonderweg nötig): sammelt 512er-Blöcke und schickt sie. */
export const WORKLET_SOURCE = `
class CatCapture extends AudioWorkletProcessor {
  constructor() { super(); this.pending = []; this.ratio = sampleRate / ${TARGET_RATE}; this.pos = 0; this.acc = 0; this.cnt = 0; }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      this.acc += channel[i]; this.cnt += 1; this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        this.pending.push(this.acc / this.cnt); this.acc = 0; this.cnt = 0;
        if (this.pending.length === ${FRAME_SAMPLES}) {
          const out = new Int16Array(${FRAME_SAMPLES});
          for (let k = 0; k < ${FRAME_SAMPLES}; k++) {
            const s = Math.max(-1, Math.min(1, this.pending[k]));
            out[k] = s < 0 ? s * 32768 : s * 32767;
          }
          this.port.postMessage(out.buffer, [out.buffer]);
          this.pending = [];
        }
      }
    }
    return true;
  }
}
registerProcessor('cat-capture', CatCapture);
`;

export function micAvailability(secure: boolean, hasMedia: boolean): string | null {
  if (!secure) return "Das Mikrofon braucht HTTPS oder localhost. Auf http://<IP> sperrt es der Browser.";
  if (!hasMedia) return "Dieser Browser bietet keinen Mikrofonzugriff.";
  return null;
}

export function formatLatency(e: Extract<VoiceEvent, { type: "voice.latency" }>): string {
  const first = e.first_audio_ms ?? e.total_ms;
  const seconds = (first / 1000).toFixed(1).replace(".", ",");
  const parts = [`Antwort nach ${seconds} s`, `Erkennung ${e.stt_ms} ms`];
  if (e.first_token_ms !== null) parts.push(`erstes Wort ${e.first_token_ms} ms`);
  if (e.via_fastpath) parts.push("ohne LLM");
  return parts.join(" · ");
}

export interface VoiceCallbacks {
  onState: (state: MicState) => void;
  onEvent: (event: VoiceEvent) => void;
  onError: (message: string) => void;
}

/** Eine Sprachsitzung: Mikrofon -> WebSocket, Antwort-Audio -> Lautsprecher. */
export class VoiceClient {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private playAt = 0;
  private rate = 22050;
  private pendingEnd = false;
  private active = 0;

  constructor(private readonly cb: VoiceCallbacks) {}

  async start(): Promise<void> {
    this.cb.onState("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      this.ctx = new AudioContext();
      void this.ctx.resume().catch(() => {});
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "text/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      this.node = new AudioWorkletNode(this.ctx, "cat-capture");
      this.ctx.createMediaStreamSource(this.stream).connect(this.node);
    } catch {
      this.cb.onError("Mikrofon nicht verfügbar oder nicht erlaubt.");
      this.stop();
      return;
    }
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${window.location.host}/ws/voice`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (msg) => this.onMessage(msg);
    ws.onclose = (e) => {
      // Ungewöhnliches Ende (nicht von uns, nicht sauber): Code und Grund nennen, das hilft bei der Suche.
      if (this.ws === ws && e.code !== 1000 && e.code !== 1005) {
        this.cb.onError(`Sprachverbindung beendet (Code ${e.code}${e.reason ? `: ${e.reason}` : ""}).`);
      }
      this.stop();
    };
    ws.onerror = () => this.cb.onError("Sprachverbindung gestört.");
    if (this.node) {
      this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(e.data);
      };
    }
  }

  private onMessage(msg: MessageEvent): void {
    if (typeof msg.data !== "string") {
      this.play(new Int16Array(msg.data as ArrayBuffer));
      return;
    }
    const event = parseVoiceEvent(msg.data);
    if (!event) return;
    switch (event.type) {
      case "voice.ready":
        this.cb.onState("ready");
        break;
      case "voice.state":
        if (event.state === "idle") this.cb.onState("ready");
        else if (event.state !== "speaking") this.cb.onState(event.state);
        break;
      case "tts.start":
        this.rate = event.rate;
        this.playAt = 0;
        this.pendingEnd = false;
        this.cb.onState("speaking");
        break;
      case "tts.end":
        this.pendingEnd = true;
        if (this.active === 0) this.cb.onState("ready");
        break;
      case "error":
        this.cb.onError(event.message);
        break;
      default:
        break;
    }
    this.cb.onEvent(event);
  }

  private play(pcm: Int16Array): void {
    if (!this.ctx) return;
    const buffer = this.ctx.createBuffer(1, pcm.length, this.rate);
    buffer.copyToChannel(pcm16ToFloat(pcm) as Float32Array<ArrayBuffer>, 0);
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    const start = Math.max(this.ctx.currentTime + 0.02, this.playAt);
    source.start(start);
    this.playAt = start + buffer.duration;
    this.active += 1;
    source.onended = () => {
      this.active -= 1;
      if (this.active === 0 && this.pendingEnd) this.cb.onState("ready");
    };
  }

  /** Browser starten Audio erst nach einer Nutzeraktion: bei der ersten Berührung nachholen. */
  resume(): void {
    if (this.ctx && this.ctx.state === "suspended") void this.ctx.resume().catch(() => {});
  }

  stop(): void {
    this.node?.port.close();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
    this.node = null;
    this.stream = null;
    this.ctx = null;
    this.ws = null;
    this.cb.onState("off");
  }
}
