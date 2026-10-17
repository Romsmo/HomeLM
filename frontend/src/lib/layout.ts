/**
 * Freier Arbeitsraum: Jedes Element hat ein Rechteck in Anteilen der Fläche (0 bis 1). So bleibt
 * die Anordnung bei jeder Fenstergröße gleich proportioniert, und die Elemente skalieren mit.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type ItemId =
  | "date"
  | "clock"
  | "system"
  | "uptime"
  | "weather"
  | "devices"
  | "files"
  | "core"
  | "caption"
  | "stage";

/** `fixed`: bleibt an seinem Platz (Cat in der Mitte), lässt sich nicht verschieben oder skalieren. */
export const ITEM_META: Record<ItemId, { label: string; hideable: boolean; fixed?: boolean }> = {
  date: { label: "Datum", hideable: true },
  clock: { label: "Uhr", hideable: true },
  system: { label: "System", hideable: true },
  uptime: { label: "Uptime", hideable: true },
  weather: { label: "Wetter", hideable: true },
  devices: { label: "Geräte", hideable: true },
  files: { label: "Dateien", hideable: true },
  core: { label: "Cat", hideable: false, fixed: true },
  caption: { label: "Sprache", hideable: false, fixed: true },
  stage: { label: "Stage", hideable: false },
};

export const ITEM_IDS = Object.keys(ITEM_META) as ItemId[];

/** Anordnung wie in den Vorlagen: links Datum und System, Mitte Cat, rechts Wetter und Geräte. */
export const DEFAULT_RECTS: Record<ItemId, Rect> = {
  date: { x: 0.01, y: 0.02, w: 0.17, h: 0.28 },
  system: { x: 0.01, y: 0.32, w: 0.2, h: 0.38 },
  uptime: { x: 0.01, y: 0.72, w: 0.2, h: 0.26 },
  core: { x: 0.26, y: 0.03, w: 0.48, h: 0.75 },
  caption: { x: 0.26, y: 0.8, w: 0.48, h: 0.18 },
  clock: { x: 0.64, y: 0.03, w: 0.11, h: 0.18 },
  weather: { x: 0.79, y: 0.02, w: 0.2, h: 0.4 },
  devices: { x: 0.79, y: 0.44, w: 0.2, h: 0.3 },
  files: { x: 0.79, y: 0.76, w: 0.2, h: 0.22 },
  stage: { x: 0.22, y: 0.03, w: 0.56, h: 0.78 },
};

export const MIN_W = 0.07;
export const MIN_H = 0.07;
const STEP = 0.005;

const round = (v: number) => Number((Math.round(v / STEP) * STEP).toFixed(4));

/** Hält ein Rechteck in der Fläche und über der Mindestgröße (Raster 0,5 %). */
export function clampRect(r: Rect): Rect {
  const w = Math.min(1, Math.max(MIN_W, r.w));
  const h = Math.min(1, Math.max(MIN_H, r.h));
  const x = Math.min(1 - w, Math.max(0, r.x));
  const y = Math.min(1 - h, Math.max(0, r.y));
  return { x: round(x), y: round(y), w: round(w), h: round(h) };
}

export function moveRect(r: Rect, dx: number, dy: number): Rect {
  return clampRect({ ...r, x: r.x + dx, y: r.y + dy });
}

export type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

/** Zieht eine Kante oder Ecke; die gegenüberliegende Seite bleibt stehen. */
export function resizeRect(r: Rect, handle: Handle, dx: number, dy: number): Rect {
  let { x, y, w, h } = r;
  if (handle.includes("e")) w = Math.max(MIN_W, Math.min(1 - x, r.w + dx));
  if (handle.includes("s")) h = Math.max(MIN_H, Math.min(1 - y, r.h + dy));
  if (handle.includes("w")) {
    const right = r.x + r.w;
    x = Math.min(right - MIN_W, Math.max(0, r.x + dx));
    w = right - x;
  }
  if (handle.includes("n")) {
    const bottom = r.y + r.h;
    y = Math.min(bottom - MIN_H, Math.max(0, r.y + dy));
    h = bottom - y;
  }
  return clampRect({ x, y, w, h });
}

export interface LayoutState {
  rects: Record<ItemId, Rect>;
  /** Stapelfolge, der letzte liegt oben. */
  order: ItemId[];
  hidden: ItemId[];
}

export const STORAGE_KEY = "cat.layout.v1";

export function defaultLayout(): LayoutState {
  return {
    rects: { ...DEFAULT_RECTS },
    // Cat unten, die Stage über allem, Widgets dazwischen.
    order: ["core", "caption", "date", "clock", "system", "uptime", "weather", "devices", "files", "stage"],
    hidden: [],
  };
}

function isRect(v: unknown): v is Rect {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return ["x", "y", "w", "h"].every((k) => typeof r[k] === "number" && Number.isFinite(r[k] as number));
}

/** Liest gespeicherte Daten; Unbrauchbares fällt auf die Vorgabe zurück, neue Elemente kommen dazu. */
export function parseLayout(raw: string | null): LayoutState {
  const base = defaultLayout();
  if (!raw) return base;
  try {
    const data: unknown = JSON.parse(raw);
    if (typeof data !== "object" || data === null) return base;
    const d = data as { rects?: Record<string, unknown>; order?: unknown; hidden?: unknown };
    for (const id of ITEM_IDS) {
      const saved = d.rects?.[id];
      if (!ITEM_META[id].fixed && isRect(saved)) base.rects[id] = clampRect(saved);
    }
    if (Array.isArray(d.order)) {
      const known = d.order.filter((id): id is ItemId => ITEM_IDS.includes(id as ItemId));
      const missing = base.order.filter((id) => !known.includes(id));
      base.order = [...known, ...missing];
    }
    if (Array.isArray(d.hidden)) {
      base.hidden = d.hidden.filter((id): id is ItemId => ITEM_IDS.includes(id as ItemId) && ITEM_META[id as ItemId].hideable);
    }
  } catch {
    return defaultLayout();
  }
  return base;
}

export function bringToFront(order: ItemId[], id: ItemId): ItemId[] {
  return order[order.length - 1] === id ? order : [...order.filter((x) => x !== id), id];
}
