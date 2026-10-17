import { type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { type Handle, ITEM_META, type ItemId, type Rect, moveRect, resizeRect } from "../../lib/layout";

const HANDLES: { id: Handle; cls: string; cursor: string }[] = [
  { id: "nw", cls: "-top-1.5 -left-1.5", cursor: "nwse-resize" },
  { id: "ne", cls: "-top-1.5 -right-1.5", cursor: "nesw-resize" },
  { id: "sw", cls: "-bottom-1.5 -left-1.5", cursor: "nesw-resize" },
  { id: "se", cls: "-right-1.5 -bottom-1.5", cursor: "nwse-resize" },
  { id: "n", cls: "-top-1.5 left-1/2 -translate-x-1/2", cursor: "ns-resize" },
  { id: "s", cls: "-bottom-1.5 left-1/2 -translate-x-1/2", cursor: "ns-resize" },
  { id: "w", cls: "top-1/2 -left-1.5 -translate-y-1/2", cursor: "ew-resize" },
  { id: "e", cls: "top-1/2 -right-1.5 -translate-y-1/2", cursor: "ew-resize" },
];

const KEY_STEP = 0.01;
const ARROWS: Record<string, [number, number] | undefined> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/**
 * Ein Element im freien Arbeitsraum. Im Anpassen-Modus lässt es sich greifen und verschieben,
 * an Ecken und Kanten skalieren, per Pfeiltasten bewegen (mit Umschalt: Größe) und ausblenden.
 */
export default function CanvasItem({
  id,
  rect,
  z,
  editing,
  canvas,
  onChange,
  onCommit,
  onFront,
  onHide,
  children,
}: {
  id: ItemId;
  rect: Rect;
  z: number;
  editing: boolean;
  canvas: RefObject<HTMLElement | null>;
  onChange: (id: ItemId, rect: Rect) => void;
  onCommit: () => void;
  onFront: (id: ItemId) => void;
  onHide?: (id: ItemId) => void;
  children: ReactNode;
}) {
  const meta = ITEM_META[id];

  /** Zieht per Zeiger: Bewegung in Anteilen der Fläche, Ereignisse am Fenster (auch außerhalb). */
  function begin(e: ReactPointerEvent, apply: (start: Rect, dx: number, dy: number) => Rect) {
    const box = canvas.current?.getBoundingClientRect();
    if (!box || box.width === 0 || box.height === 0) return;
    e.preventDefault();
    e.stopPropagation();
    onFront(id);
    const start = rect;
    const origin = { x: e.clientX, y: e.clientY };
    const move = (ev: PointerEvent) => {
      onChange(id, apply(start, (ev.clientX - origin.x) / box.width, (ev.clientY - origin.y) / box.height));
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      onCommit();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }

  function onKeyDown(e: KeyboardEvent) {
    const dir = ARROWS[e.key];
    if (!dir) return;
    e.preventDefault();
    const [dx, dy] = [dir[0] * KEY_STEP, dir[1] * KEY_STEP];
    onChange(id, e.shiftKey ? resizeRect(rect, "se", dx, dy) : moveRect(rect, dx, dy));
    onCommit();
  }

  return (
    <div
      data-item={id}
      className="absolute"
      style={{
        left: `${rect.x * 100}%`,
        top: `${rect.y * 100}%`,
        width: `${rect.w * 100}%`,
        height: `${rect.h * 100}%`,
        zIndex: z,
      }}
      onPointerDown={() => onFront(id)}
    >
      <div className="h-full w-full">{children}</div>
      {editing && (
        <div
          role="group"
          tabIndex={0}
          aria-label={`${meta.label}: mit der Maus ziehen oder Pfeiltasten zum Verschieben, Umschalt plus Pfeiltasten zum Skalieren`}
          onPointerDown={(e) => begin(e, (start, dx, dy) => moveRect(start, dx, dy))}
          onKeyDown={onKeyDown}
          className="absolute inset-0 z-10 cursor-move touch-none border border-dashed border-cyan-300/80 bg-cyan-400/5 outline-none focus-visible:border-solid focus-visible:ring-2 focus-visible:ring-cyan-300"
        >
          <span className="pointer-events-none absolute top-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[0.65rem] tracking-widest text-cyan-200 uppercase">
            {meta.label}
          </span>
          {meta.hideable && onHide && (
            <button
              type="button"
              aria-label={`${meta.label} ausblenden`}
              title="Ausblenden"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => onHide(id)}
              className="absolute top-1 right-1 grid h-5 w-5 cursor-pointer place-items-center rounded bg-black/70 text-cyan-200 hover:text-rose-300"
            >
              <svg width="9" height="9" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M2 2l8 8M10 2 2 10" />
              </svg>
            </button>
          )}
          {HANDLES.map((h) => (
            <span
              key={h.id}
              data-handle={h.id}
              onPointerDown={(e) => begin(e, (start, dx, dy) => resizeRect(start, h.id, dx, dy))}
              className={`absolute h-3 w-3 touch-none border border-cyan-200 bg-black ${h.cls}`}
              style={{ cursor: h.cursor }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
