import { useCallback, useState } from "react";
import {
  type ItemId,
  type LayoutState,
  type Rect,
  STORAGE_KEY,
  bringToFront,
  defaultLayout,
  parseLayout,
} from "../lib/layout";

function load(): LayoutState {
  try {
    return parseLayout(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return defaultLayout();
  }
}

function save(state: LayoutState): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Speicher gesperrt: die Anordnung gilt dann nur bis zum Neuladen
  }
}

/** Anordnung der Arbeitsraum-Elemente; wird im Browser gespeichert (pro Gerät). */
export function useLayout() {
  const [state, setState] = useState<LayoutState>(load);

  /** Während des Ziehens: nur im Speicher ändern. */
  const setRect = useCallback((id: ItemId, rect: Rect) => {
    setState((s) => ({ ...s, rects: { ...s.rects, [id]: rect } }));
  }, []);

  const front = useCallback((id: ItemId) => {
    setState((s) => (s.order[s.order.length - 1] === id ? s : { ...s, order: bringToFront(s.order, id) }));
  }, []);

  /** Am Ende einer Geste: speichern. */
  const commit = useCallback(() => {
    setState((s) => {
      save(s);
      return s;
    });
  }, []);

  const hide = useCallback((id: ItemId) => {
    setState((s) => {
      const next = s.hidden.includes(id) ? s : { ...s, hidden: [...s.hidden, id] };
      save(next);
      return next;
    });
  }, []);

  const show = useCallback((id: ItemId) => {
    setState((s) => {
      const next = { ...s, hidden: s.hidden.filter((x) => x !== id), order: bringToFront(s.order, id) };
      save(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    const next = defaultLayout();
    save(next);
    setState(next);
  }, []);

  return { state, setRect, front, commit, hide, show, reset };
}
