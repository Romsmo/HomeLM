import { useCallback, useEffect, useState } from "react";

export type UiMode = "mobile" | "desktop";

const KEY = "cat.ui";
/** Handy hochkant, Handy quer und kleine Touch-Geräte. Tablets und Laptops bleiben beim Arbeitsraum. */
const PHONE_QUERY = "(max-width: 700px), (pointer: coarse) and (max-width: 900px)";

/**
 * Welche Oberfläche? Reihenfolge: `?ui=mobile|desktop` in der Adresse (wird gemerkt, `?ui=auto`
 * löscht das), sonst die gemerkte Wahl, sonst die Bildschirmgröße.
 */
export function detectUi(search: string, stored: string | null, phone: boolean): UiMode {
  const param = new URLSearchParams(search).get("ui");
  if (param === "mobile" || param === "desktop") return param;
  if (stored === "mobile" || stored === "desktop") return stored;
  return phone ? "mobile" : "desktop";
}

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // Speicher gesperrt (privates Fenster): dann gilt die Bildschirmgröße
  }
}

function write(value: UiMode | null): void {
  try {
    if (value) window.localStorage.setItem(KEY, value);
    else window.localStorage.removeItem(KEY);
  } catch {
    // ohne Speicher gilt die Wahl nur für diese Sitzung
  }
}

function isPhone(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(PHONE_QUERY).matches
    : false;
}

export function useUiMode(): [UiMode, (mode: UiMode | "auto") => void] {
  const [mode, setMode] = useState<UiMode>(() => {
    const param = new URLSearchParams(window.location.search).get("ui");
    if (param === "mobile" || param === "desktop") write(param);
    else if (param === "auto") write(null);
    return detectUi(window.location.search, read(), isPhone());
  });

  // Folgt der Bildschirmgröße (Drehen, Fenstergröße), solange nichts gewählt wurde.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(PHONE_QUERY);
    const onChange = () => {
      if (!read() && !new URLSearchParams(window.location.search).get("ui")) {
        setMode(list.matches ? "mobile" : "desktop");
      }
    };
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, []);

  const choose = useCallback((next: UiMode | "auto") => {
    write(next === "auto" ? null : next);
    // `?ui=` aus der Adresse nehmen, sonst gewänne es gegen die neue Wahl.
    const url = new URL(window.location.href);
    url.searchParams.delete("ui");
    window.history.replaceState(null, "", url.toString());
    setMode(next === "auto" ? (isPhone() ? "mobile" : "desktop") : next);
  }, []);

  return [mode, choose];
}
