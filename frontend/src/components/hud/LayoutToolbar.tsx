import { ITEM_META, type ItemId } from "../../lib/layout";

/** Schalter für den Anpassen-Modus, Zurücksetzen und das Wiederholen ausgeblendeter Elemente. */
export default function LayoutToolbar({
  editing,
  hidden,
  onToggle,
  onReset,
  onShow,
}: {
  editing: boolean;
  hidden: ItemId[];
  onToggle: () => void;
  onReset: () => void;
  onShow: (id: ItemId) => void;
}) {
  return (
    <div className="absolute bottom-2 left-2 z-40 flex max-w-[60%] flex-wrap items-center gap-1.5 text-xs">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={editing}
        title="Elemente verschieben und skalieren"
        className={`hud-btn rounded-md bg-black/60 px-2.5 py-1 ${editing ? "!border-cyan-300 text-cyan-50" : "opacity-70 hover:opacity-100"}`}
      >
        {editing ? "Fertig" : "Layout anpassen"}
      </button>
      {editing && (
        <>
          <button type="button" onClick={onReset} className="hud-btn rounded-md bg-black/60 px-2.5 py-1">
            Zurücksetzen
          </button>
          {hidden.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => onShow(id)}
              aria-label={`${ITEM_META[id].label} wieder einblenden`}
              className="hud-btn rounded-md bg-black/60 px-2 py-1"
            >
              + {ITEM_META[id].label}
            </button>
          ))}
        </>
      )}
    </div>
  );
}
