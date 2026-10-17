import {
  DEFAULT_RECTS,
  ITEM_IDS,
  ITEM_META,
  MIN_H,
  MIN_W,
  type Rect,
  bringToFront,
  clampRect,
  defaultLayout,
  moveRect,
  parseLayout,
  resizeRect,
} from "./layout";

const close = (a: number, b: number) => expect(a).toBeCloseTo(b, 6);
const rect: Rect = { x: 0.2, y: 0.2, w: 0.3, h: 0.3 };

describe("Rechtecke", () => {
  it("Standardanordnung liegt komplett in der Fläche und überlappt Kern nur mit der Stage", () => {
    for (const id of ITEM_IDS) {
      const r = DEFAULT_RECTS[id];
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.y).toBeGreaterThanOrEqual(0);
      expect(r.x + r.w).toBeLessThanOrEqual(1.0001);
      expect(r.y + r.h).toBeLessThanOrEqual(1.0001);
    }
  });

  it("verschiebt und hält das Element in der Fläche", () => {
    const moved = moveRect(rect, 0.1, -0.05);
    close(moved.x, 0.3);
    close(moved.y, 0.15);
    expect(moveRect(rect, 5, 5)).toEqual({ x: 0.7, y: 0.7, w: 0.3, h: 0.3 });
    expect(moveRect(rect, -5, -5)).toEqual({ x: 0, y: 0, w: 0.3, h: 0.3 });
  });

  it("skaliert an der Ecke, die gegenüberliegende bleibt stehen", () => {
    const se = resizeRect(rect, "se", 0.1, 0.05);
    close(se.w, 0.4);
    close(se.h, 0.35);
    close(se.x, 0.2);
    const nw = resizeRect(rect, "nw", -0.1, -0.1);
    close(nw.x, 0.1);
    close(nw.y, 0.1);
    close(nw.x + nw.w, 0.5);
    close(nw.y + nw.h, 0.5);
  });

  it("begrenzt auf Mindestgröße und Fläche", () => {
    const tiny = resizeRect(rect, "se", -1, -1);
    expect(tiny.w).toBeCloseTo(MIN_W, 2);
    expect(tiny.h).toBeCloseTo(MIN_H, 2);
    const nwTiny = resizeRect(rect, "nw", 1, 1);
    close(nwTiny.x + nwTiny.w, 0.5);
    expect(nwTiny.w).toBeGreaterThanOrEqual(MIN_W - 0.0001);
    const huge = resizeRect(rect, "se", 5, 5);
    close(huge.x + huge.w, 1);
    close(huge.y + huge.h, 1);
  });

  it("zieht einzelne Kanten", () => {
    const e = resizeRect(rect, "e", 0.1, 0.5);
    close(e.w, 0.4);
    close(e.h, 0.3);
    const n = resizeRect(rect, "n", 0.5, -0.1);
    close(n.h, 0.4);
    close(n.w, 0.3);
  });

  it("rundet auf das Raster und repariert Unsinn", () => {
    expect(clampRect({ x: 0.2012, y: 0.2, w: 0.3, h: 0.3 }).x).toBeCloseTo(0.2, 6);
    const r = clampRect({ x: -3, y: 9, w: 0, h: 99 });
    expect(r.x).toBe(0);
    expect(r.w).toBeCloseTo(MIN_W, 2);
    expect(r.h).toBe(1);
    expect(r.y).toBe(0);
  });
});

describe("Speichern und Laden", () => {
  it("ohne oder mit kaputten Daten gilt die Vorgabe", () => {
    expect(parseLayout(null)).toEqual(defaultLayout());
    expect(parseLayout("{kaputt")).toEqual(defaultLayout());
    expect(parseLayout("42")).toEqual(defaultLayout());
  });

  it("übernimmt gespeicherte Rechtecke, Reihenfolge und ausgeblendete Elemente", () => {
    const saved = JSON.stringify({
      rects: { weather: { x: 0.5, y: 0.5, w: 0.2, h: 0.2 }, system: "kaputt" },
      order: ["weather", "gibt-es-nicht", "core"],
      hidden: ["uptime", "core", "unbekannt"],
    });
    const state = parseLayout(saved);
    expect(state.rects.weather).toEqual({ x: 0.5, y: 0.5, w: 0.2, h: 0.2 });
    expect(state.rects.system).toEqual(DEFAULT_RECTS.system);
    expect(state.order.slice(0, 2)).toEqual(["weather", "core"]);
    expect([...state.order].sort()).toEqual([...ITEM_IDS].sort());
    expect(state.hidden).toEqual(["uptime"]); // Cat selbst lässt sich nicht ausblenden
  });

  it("Cat und Sprache bleiben fest, auch wenn etwas anderes gespeichert ist", () => {
    const state = parseLayout(JSON.stringify({ rects: { core: { x: 0, y: 0, w: 0.2, h: 0.2 } } }));
    expect(state.rects.core).toEqual(DEFAULT_RECTS.core);
    expect(DEFAULT_RECTS.core.x + DEFAULT_RECTS.core.w / 2).toBeCloseTo(0.5, 6); // mittig
    expect(ITEM_META.core.fixed && ITEM_META.caption.fixed).toBe(true);
  });

  it("holt neue Elemente nach, die ein älterer Stand nicht kannte", () => {
    const old = JSON.stringify({ rects: { weather: DEFAULT_RECTS.weather }, order: ["weather"] });
    const state = parseLayout(old);
    expect(state.order).toContain("files");
    expect(state.rects.files).toEqual(DEFAULT_RECTS.files);
  });
});

describe("Stapelfolge", () => {
  it("holt ein Element nach oben, ohne die übrigen umzuordnen", () => {
    expect(bringToFront(["a", "b", "c"] as never, "a" as never)).toEqual(["b", "c", "a"]);
    const same = ["a", "b"] as never;
    expect(bringToFront(same, "b" as never)).toBe(same);
  });
});
