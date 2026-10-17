import { type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { ITEM_META, type ItemId, type Rect, moveRect, resizeRect } from "../../lib/layout";

const KEY_STEP = 0.01;
const ARROWS: Record<string, [number, number] | undefined> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/**
 * Ein Element im freien Arbeitsraum, bedienbar wie ein Fenster: am schmalen Balken oben greifen und
 * verschieben, an der Ecke unten rechts ziehen zum Skalieren. Der Balken liegt im Rand des
 * Elements, der Inhalt bleibt voll bedienbar. Mit der Tastatur: Balken fokussieren, Pfeiltasten
 * verschieben, Umschalt plus Pfeiltasten skalieren. `fixed` (Cat in der Mitte) hat keine Griffe.
 */
export default function CanvasItem({
  id,
  rect,
  z,
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
  canvas: RefObject<HTMLElement | null>;
  onChange: (id: ItemId, rect: Rect) => void;
  onCommit: () => void;
  onFront: (id: ItemId) => void;
  onHide?: (id: ItemId) => void;
  children: ReactNode;
}) {
  const meta = ITEM_META[id];
  const style = {
    left: `${rect.x * 100}%`,
    top: `${rect.y * 100}%`,
    width: `${rect.w * 100}%`,
    height: `${rect.h * 100}%`,
    zIndex: z,
  };

  if (meta.fixed) {
    return (
      <div data-item={id} className="absolute" style={style}>
        {children}
      </div>
    );
  }

  /** Zieht per Zeiger: Bewegung in Anteilen der Fläche, Ereignisse am Fenster (auch außerhalb). */
  function begin(e: ReactPointerEvent, apply: (start: Rect, dx: number, dy: number) => Rect) {
    const box = canvas.current?.getBoundingClientRect();
    if (!box || box.width === 0 || box.height === 0) return;
    e.preventDefault();
    e.stopPropagation();
    onFront(id);
    // Beim Ziehen nichts markieren (auch nicht, wenn der Zeiger über anderen Text fährt).
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    window.getSelection?.()?.removeAllRanges();
    const start = rect;
    const origin = { x: e.clientX, y: e.clientY };
    const move = (ev: PointerEvent) => {
      onChange(id, apply(start, (ev.clientX - origin.x) / box.width, (ev.clientY - origin.y) / box.height));
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      document.body.style.userSelect = previous;
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
    <div data-item={id} className="group absolute" style={style} onPointerDown={() => onFront(id)}>
      <div className="h-full w-full">{children}</div>

      <div
        role="group"
        tabIndex={0}
        aria-label={`${meta.label}: am Balken ziehen oder Pfeiltasten zum Verschieben, Umschalt plus Pfeiltasten zum Skalieren`}
        title={`${meta.label} verschieben`}
        onPointerDown={(e) => begin(e, (start, dx, dy) => moveRect(start, dx, dy))}
        onKeyDown={onKeyDown}
        className="absolute inset-x-0 top-0 z-10 flex h-3 cursor-grab touch-none items-center justify-center outline-none active:cursor-grabbing"
      >
        <span
          aria-hidden
          className="h-0.5 w-8 rounded-full bg-cyan-300/30 transition group-hover:bg-cyan-300/90 group-focus-within:bg-cyan-300"
        />
        {meta.hideable && onHide && (
          <button
            type="button"
            aria-label={`${meta.label} ausblenden`}
            title="Ausblenden"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onHide(id)}
            className="absolute top-0 right-3 grid h-3 w-3 cursor-pointer place-items-center text-cyan-200/0 transition group-hover:text-cyan-200/80 hover:!text-rose-300 focus-visible:text-cyan-100"
          >
            <svg width="7" height="7" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="2.4" aria-hidden>
              <path d="M2 2l8 8M10 2 2 10" />
            </svg>
          </button>
        )}
      </div>

      <span
        data-handle="se"
        title="Größe ändern"
        onPointerDown={(e) => begin(e, (start, dx, dy) => resizeRect(start, "se", dx, dy))}
        className="absolute right-0 bottom-0 z-10 grid h-4 w-4 cursor-nwse-resize touch-none place-items-end text-cyan-300/30 transition group-hover:text-cyan-300/90"
      >
        <svg width="11" height="11" viewBox="0 0 11 11" stroke="currentColor" strokeWidth="1.4" aria-hidden>
          <path d="M10 3 3 10M10 7 7 10" />
        </svg>
      </span>
    </div>
  );
}
