import { useRef, useState } from "react";
import { type FileEntry, formatSize } from "../../lib/upload";
import { HudPanel } from "./Hud";

const KIND: Record<FileEntry["kind"], string> = { image: "Bild", text: "Text", other: "Datei" };

/** Dateieingang: abgelegte Dateien, auf der Stage zeigen, löschen, Dateien auswählen. */
export default function FilesPanel({
  files,
  error,
  onPick,
  onShow,
  onDelete,
}: {
  files: FileEntry[];
  error: string | null;
  onPick: (files: File[]) => void;
  onShow: (name: string) => void;
  onDelete: (name: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <HudPanel
      title="Dateien"
      action={
        <>
          <button type="button" onClick={() => input.current?.click()} className="hud-btn rounded-md px-2 py-0.5 text-xs">
            Datei wählen
          </button>
          <input
            ref={input}
            type="file"
            multiple
            hidden
            aria-label="Dateien auswählen"
            onChange={(e) => {
              const picked = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (picked.length > 0) onPick(picked);
            }}
          />
        </>
      }
    >
      {error && (
        <p role="alert" className="mb-1 text-xs text-rose-400">
          {error}
        </p>
      )}
      {files.length === 0 ? (
        <p className="text-sm text-cyan-200/50">Dateien einfach hierher oder irgendwo ins Fenster ziehen.</p>
      ) : (
        <ul className="grid gap-1 text-sm" aria-label="Abgelegte Dateien">
          {files.map((f) => (
            <li key={f.name} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="w-9 shrink-0 text-[0.65rem] tracking-wider text-cyan-300/60 uppercase">{KIND[f.kind]}</span>
              <span className="min-w-[5rem] flex-1 truncate text-cyan-100/90" title={f.name}>
                {f.name}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-cyan-200/50">{formatSize(f.size)}</span>
              {f.kind !== "other" && (
                <button
                  type="button"
                  onClick={() => onShow(f.name)}
                  aria-label={`${f.name} anzeigen`}
                  className="hud-btn shrink-0 rounded px-1.5 text-xs"
                >
                  Zeigen
                </button>
              )}
              <a
                href={`/api/files/${encodeURIComponent(f.name)}`}
                download={f.name}
                aria-label={`${f.name} herunterladen`}
                className="hud-btn shrink-0 rounded px-1.5 text-xs"
              >
                Laden
              </a>
              <button
                type="button"
                aria-label={confirming === f.name ? `${f.name} wirklich löschen` : `${f.name} löschen`}
                onClick={() => {
                  if (confirming === f.name) {
                    setConfirming(null);
                    onDelete(f.name);
                  } else {
                    setConfirming(f.name);
                    setTimeout(() => setConfirming((c) => (c === f.name ? null : c)), 3000);
                  }
                }}
                className={`shrink-0 rounded border px-1.5 text-xs ${
                  confirming === f.name
                    ? "border-rose-400 text-rose-300"
                    : "border-cyan-400/20 text-cyan-200/60 hover:border-rose-400 hover:text-rose-300"
                }`}
              >
                {confirming === f.name ? "Sicher?" : "×"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </HudPanel>
  );
}
