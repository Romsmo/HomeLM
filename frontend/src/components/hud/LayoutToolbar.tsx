import { ITEM_META, type ItemId } from "../../lib/layout";

/** Ausgeblendete Elemente zurückholen und die Anordnung zurücksetzen (immer verfügbar, dezent). */
export default function LayoutToolbar({
  hidden,
  onReset,
  onShow,
}: {
  hidden: ItemId[];
  onReset: () => void;
  onShow: (id: ItemId) => void;
}) {
  return (
    <div className="absolute bottom-1 left-1 z-[60] flex max-w-[60%] flex-wrap items-center gap-1.5 text-xs opacity-50 transition hover:opacity-100 focus-within:opacity-100">
      {hidden.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onShow(id)}
          aria-label={`${ITEM_META[id].label} wieder einblenden`}
          className="hud-btn rounded-md bg-black/70 px-2 py-1"
        >
          + {ITEM_META[id].label}
        </button>
      ))}
      <button
        type="button"
        onClick={onReset}
        title="Alle Elemente an ihren Standardplatz"
        className="hud-btn rounded-md bg-black/70 px-2 py-1"
      >
        Layout zurücksetzen
      </button>
    </div>
  );
}
