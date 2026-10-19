/** Gedächtnis (Second Brain), Personen und Füllsätze: ansehen und einzeln vergessen. */

export interface NoteRow {
  path: string;
  topic: string;
  title: string;
  date: string;
  tags: string[];
  text: string;
}

export interface PersonRow {
  id: string;
  name: string;
  created: number;
  last_seen: number | null;
  /** Ist eine Stimme gespeichert (mit Zustimmung)? */
  voice: boolean;
  samples: number;
}

export interface PeopleInfo {
  enabled: boolean;
  voiceAvailable: boolean;
  people: PersonRow[];
}

export interface FillerRow {
  text: string;
  category: string;
  source: string;
  uses: number;
  last_used: number | null;
}

async function failure(resp: Response): Promise<Error> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return new Error(body.detail);
  } catch {
    // keine JSON-Antwort
  }
  return new Error(resp.status === 401 ? "Bitte erneut anmelden." : `Fehler ${resp.status}`);
}

async function getJson(url: string): Promise<unknown> {
  const resp = await fetch(url, { credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
  return resp.json();
}

async function del(url: string): Promise<void> {
  const resp = await fetch(url, { method: "DELETE", credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
}

export async function listNotes(): Promise<NoteRow[]> {
  const data = await getJson("/api/memory");
  return Array.isArray(data) ? (data as NoteRow[]) : [];
}

export const deleteNote = (path: string) => del(`/api/memory?path=${encodeURIComponent(path)}`);

export async function listPeople(): Promise<PeopleInfo> {
  const data = await getJson("/api/people");
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { enabled: false, voiceAvailable: false, people: [] };
  }
  const d = data as { enabled?: boolean; voice_available?: boolean; people?: PersonRow[] };
  return { enabled: !!d.enabled, voiceAvailable: !!d.voice_available, people: d.people ?? [] };
}

export const forgetVoice = (id: string) => del(`/api/people/${encodeURIComponent(id)}/voice`);
export const forgetPerson = (id: string) => del(`/api/people/${encodeURIComponent(id)}`);

export async function listFillers(): Promise<FillerRow[]> {
  const data = await getJson("/api/fillers");
  return Array.isArray(data) ? (data as FillerRow[]) : [];
}

export const deleteFiller = (text: string) => del(`/api/fillers?text=${encodeURIComponent(text)}`);
