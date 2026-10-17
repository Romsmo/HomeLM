export interface FileEntry {
  name: string;
  size: number;
  kind: "image" | "text" | "other";
  modified: number;
}

/** Muss zum Server passen (backend/src/cat/files.py). */
export const MAX_FILE_BYTES = 25 * 1024 * 1024;

const url = (name: string) => `/api/files/${encodeURIComponent(name)}`;

async function failure(resp: Response): Promise<Error> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return new Error(body.detail);
  } catch {
    // keine JSON-Antwort
  }
  return new Error(resp.status === 401 ? "Bitte erneut anmelden." : `Fehler ${resp.status}`);
}

export async function uploadFile(file: File): Promise<FileEntry> {
  if (file.size === 0) throw new Error("Die Datei ist leer.");
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(`Zu groß (höchstens ${Math.round(MAX_FILE_BYTES / 1024 / 1024)} MB).`);
  }
  const resp = await fetch(url(file.name || "datei"), {
    method: "PUT",
    body: file,
    credentials: "same-origin",
    headers: { "Content-Type": "application/octet-stream" },
  });
  if (!resp.ok) throw await failure(resp);
  return (await resp.json()) as FileEntry;
}

export async function listFiles(): Promise<FileEntry[]> {
  const resp = await fetch("/api/files", { credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
  return (await resp.json()) as FileEntry[];
}

export async function deleteFile(name: string): Promise<void> {
  const resp = await fetch(url(name), { method: "DELETE", credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
}

export async function showFile(name: string): Promise<void> {
  const resp = await fetch(`${url(name)}/show`, { method: "POST", credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1).replace(".", ",")} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
