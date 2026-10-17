export interface LearnedRow {
  id: string;
  phrase: string;
  does: string;
  active: boolean;
  seen: number;
  needed: number;
  uses: number;
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

export async function listLearned(): Promise<LearnedRow[]> {
  const resp = await fetch("/api/learned", { credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
  const data: unknown = await resp.json();
  return Array.isArray(data) ? (data as LearnedRow[]) : [];
}

export async function forgetLearned(id: string): Promise<void> {
  const resp = await fetch(`/api/learned/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
}

export async function forgetAllLearned(): Promise<void> {
  const resp = await fetch("/api/learned", { method: "DELETE", credentials: "same-origin" });
  if (!resp.ok) throw await failure(resp);
}
