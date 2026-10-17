import { useCallback, useEffect, useRef, useState } from "react";
import { type FileEntry, deleteFile, listFiles, showFile, uploadFile } from "../lib/upload";

export interface UploadState {
  id: number;
  name: string;
  status: "uploading" | "done" | "error";
  error?: string;
}

/** Dateieingang: Liste, Upload mit Status, Löschen, auf der Stage zeigen. */
export function useFiles(connected: boolean) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [error, setError] = useState<string | null>(null);
  const counter = useRef(0);

  const refresh = useCallback(async () => {
    try {
      setFiles(await listFiles());
    } catch {
      // Liste ist nur eine Anzeige; der nächste Versuch kommt von selbst
    }
  }, []);

  useEffect(() => {
    if (connected) void refresh();
  }, [connected, refresh]);

  const patch = useCallback((id: number, change: Partial<UploadState>) => {
    setUploads((list) => list.map((u) => (u.id === id ? { ...u, ...change } : u)));
  }, []);

  const upload = useCallback(
    async (picked: File[]) => {
      for (const file of picked) {
        const id = ++counter.current;
        setUploads((list) => [...list, { id, name: file.name, status: "uploading" }]);
        try {
          await uploadFile(file);
          patch(id, { status: "done" });
          void refresh();
        } catch (e) {
          patch(id, { status: "error", error: e instanceof Error ? e.message : "Fehlgeschlagen" });
        }
        // Erledigte Meldungen verschwinden nach einer Weile, Fehler bleiben bis zum Schließen.
        setTimeout(() => setUploads((list) => list.filter((u) => !(u.id === id && u.status === "done"))), 5000);
      }
    },
    [patch, refresh],
  );

  const dismiss = useCallback((id: number) => setUploads((list) => list.filter((u) => u.id !== id)), []);

  const remove = useCallback(
    async (name: string) => {
      try {
        await deleteFile(name);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Löschen fehlgeschlagen");
      }
      void refresh();
    },
    [refresh],
  );

  const show = useCallback(async (name: string) => {
    try {
      await showFile(name);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Anzeigen fehlgeschlagen");
    }
  }, []);

  return { files, uploads, error, upload, dismiss, remove, show, refresh };
}
