import { useEffect, useState } from "react";

/**
 * Höhe des sichtbaren Bereichs. Öffnet sich die Bildschirmtastatur, schrumpft sie (iOS tut das
 * nicht mit `dvh`), und die Eingabezeile bleibt über der Tastatur sichtbar.
 */
export function useViewportHeight(): number {
  const read = () => window.visualViewport?.height ?? window.innerHeight;
  const [height, setHeight] = useState(read);
  useEffect(() => {
    const viewport = window.visualViewport;
    const update = () => {
      setHeight(read());
      window.scrollTo(0, 0); // iOS schiebt die Seite beim Tippen hoch
    };
    viewport?.addEventListener("resize", update);
    viewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    return () => {
      viewport?.removeEventListener("resize", update);
      viewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);
  return height;
}

type WakeLockSentinelLike = { release: () => Promise<void> };

/** Hält den Bildschirm an, solange `active` gilt (ein Handy, das zuhört, soll nicht einschlafen). */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    const nav = navigator as Navigator & {
      wakeLock?: { request: (type: "screen") => Promise<WakeLockSentinelLike> };
    };
    if (!active || !nav.wakeLock) return;
    let lock: WakeLockSentinelLike | null = null;
    let cancelled = false;
    const acquire = async () => {
      try {
        const next = await nav.wakeLock?.request("screen");
        if (!next) return;
        if (cancelled) void next.release().catch(() => {});
        else lock = next;
      } catch {
        // nicht erlaubt (z. B. Energiesparmodus): dann schläft der Bildschirm eben
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") void acquire();
    };
    void acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      void lock?.release().catch(() => {});
    };
  }, [active]);
}

const KEEP_KEY = "cat.keepAwake";

export function keepAwakePreferred(): boolean {
  try {
    return window.localStorage.getItem(KEEP_KEY) !== "off";
  } catch {
    return true;
  }
}

export function rememberKeepAwake(on: boolean): void {
  try {
    window.localStorage.setItem(KEEP_KEY, on ? "on" : "off");
  } catch {
    // Speicher gesperrt: gilt nur für diese Sitzung
  }
}
