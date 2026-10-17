import type { UploadState } from "../../hooks/useFiles";

/** Hervorhebung beim Ziehen und Fortschritt der Uploads. */
export default function UploadStatus({
  dragging,
  uploads,
  onDismiss,
}: {
  dragging: boolean;
  uploads: UploadState[];
  onDismiss: (id: number) => void;
}) {
  return (
    <>
      {dragging && (
        <div
          data-testid="drop-overlay"
          className="pointer-events-none fixed inset-0 z-50 grid place-items-center border-2 border-dashed border-cyan-300 bg-cyan-400/10 backdrop-blur-[2px]"
        >
          <p className="hud-text-glow rounded-xl bg-black/70 px-6 py-4 text-lg tracking-widest text-cyan-100 uppercase">
            Dateien hier ablegen
          </p>
        </div>
      )}
      {uploads.length > 0 && (
        <ul
          role="status"
          aria-live="polite"
          aria-label="Uploads"
          className="hud-panel fixed right-3 bottom-3 z-50 grid w-72 max-w-[calc(100vw-1.5rem)] gap-1 p-3 text-sm"
        >
          {uploads.map((u) => (
            <li key={u.id} className="flex items-center gap-2">
              <span
                aria-hidden
                className={`h-2 w-2 shrink-0 rounded-full ${
                  u.status === "uploading" ? "animate-pulse bg-amber-400" : u.status === "done" ? "bg-cyan-300" : "bg-rose-500"
                }`}
              />
              <span className="min-w-0 flex-1 truncate text-cyan-100">{u.name}</span>
              <span className={`shrink-0 text-xs ${u.status === "error" ? "text-rose-300" : "text-cyan-200/60"}`}>
                {u.status === "uploading" ? "lädt …" : u.status === "done" ? "abgelegt" : u.error}
              </span>
              {u.status === "error" && (
                <button type="button" onClick={() => onDismiss(u.id)} aria-label={`${u.name} schließen`} className="hud-btn rounded px-1.5 text-xs">
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
