import { useCallback, useEffect, useRef, useState } from "react";
import { type MicState, VoiceClient, formatLatency, micAvailability } from "../lib/voice";

export interface MicControl {
  state: MicState;
  /** null = nutzbar, sonst der Grund (wird als Hinweis am Knopf gezeigt). */
  unavailable: string | null;
  latency: string | null;
  error: string | null;
  toggle: () => void;
}

interface VoiceInfo {
  enabled: boolean;
  ready: boolean;
  error: string | null;
}

async function fetchInfo(): Promise<VoiceInfo | null> {
  try {
    const resp = await fetch("/api/voice", { credentials: "same-origin" });
    return resp.ok ? ((await resp.json()) as VoiceInfo) : null;
  } catch {
    return null;
  }
}

const PREF_KEY = "cat.mic";

function micWanted(): boolean {
  try {
    return window.localStorage.getItem(PREF_KEY) !== "off";
  } catch {
    return true;
  }
}

function rememberMic(on: boolean): void {
  try {
    window.localStorage.setItem(PREF_KEY, on ? "on" : "off");
  } catch {
    // Speicher gesperrt: dann gilt die Voreinstellung (an)
  }
}

/**
 * Mikrofon und Spracheingabe. Mit `autoStart` hört Cat von selbst zu, sobald Sprache auf dem
 * Server bereit ist (außer der Nutzer hat das Mikrofon ausgeschaltet; das merkt sich der Browser).
 */
export function useVoice(connected: boolean, autoStart = false): MicControl {
  const [state, setState] = useState<MicState>("off");
  const [info, setInfo] = useState<VoiceInfo | null>(null);
  const [latency, setLatency] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const client = useRef<VoiceClient | null>(null);
  const autoTried = useRef(false);

  useEffect(() => {
    if (!connected) return;
    let cancelled = false;
    void fetchInfo().then((i) => {
      if (!cancelled) setInfo(i);
    });
    return () => {
      cancelled = true;
    };
  }, [connected]);

  useEffect(() => () => client.current?.stop(), []);

  const secure = typeof window !== "undefined" && window.isSecureContext;
  const hasMedia = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  let unavailable = micAvailability(secure, hasMedia);
  if (!unavailable) {
    if (info === null) unavailable = "Sprachstatus unbekannt.";
    else if (!info.enabled) unavailable = "Die Sprachfunktion ist auf dem Server ausgeschaltet (CAT_VOICE).";
    else if (!info.ready) unavailable = info.error ?? "Die Sprachmodelle laden noch.";
  }

  const start = useCallback(() => {
    setError(null);
    const c = new VoiceClient({
      onState: (s) => {
        setState(s);
        if (s === "off") client.current = null;
      },
      onEvent: (e) => {
        if (e.type === "voice.latency") setLatency(formatLatency(e));
      },
      onError: setError,
    });
    client.current = c;
    void c.start();
  }, []);

  const toggle = useCallback(() => {
    if (client.current) {
      rememberMic(false);
      client.current.stop();
      client.current = null;
      return;
    }
    rememberMic(true);
    start();
  }, [start]);

  // Automatisch starten, sobald alles bereit ist; nach einem Verbindungsabbruch erneut versuchen.
  useEffect(() => {
    if (!connected) autoTried.current = false;
  }, [connected]);
  useEffect(() => {
    if (!autoStart || unavailable !== null || client.current || autoTried.current) return;
    if (!micWanted()) return;
    autoTried.current = true;
    start();
  }, [autoStart, unavailable, start, connected]);

  // Audio darf erst nach einer Berührung laufen: dann das Mikrofon "aufwecken".
  useEffect(() => {
    const wake = () => client.current?.resume();
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    return () => {
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
    };
  }, []);

  return { state, unavailable, latency, error, toggle };
}
