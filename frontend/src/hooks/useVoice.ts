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

export function useVoice(connected: boolean): MicControl {
  const [state, setState] = useState<MicState>("off");
  const [info, setInfo] = useState<VoiceInfo | null>(null);
  const [latency, setLatency] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const client = useRef<VoiceClient | null>(null);

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

  const toggle = useCallback(() => {
    if (client.current) {
      client.current.stop();
      client.current = null;
      return;
    }
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

  return { state, unavailable, latency, error, toggle };
}
