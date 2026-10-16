export type LoginResult =
  | { ok: true }
  | { ok: false; message: string; retryAfter?: number };

export type SessionCheck = "authenticated" | "anonymous" | "unreachable";

/** Prüft die Sitzung. "unreachable" heißt: Server nicht erreichbar, nicht etwa abgemeldet. */
export async function fetchMe(): Promise<SessionCheck> {
  try {
    const resp = await fetch("/api/me", { credentials: "same-origin" });
    if (resp.ok) return "authenticated";
    return resp.status === 401 ? "anonymous" : "unreachable";
  } catch {
    return "unreachable";
  }
}

export async function login(password: string): Promise<LoginResult> {
  try {
    const resp = await fetch("/api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (resp.ok) return { ok: true };
    if (resp.status === 401) return { ok: false, message: "Falsches Passwort." };
    if (resp.status === 429) {
      const retryAfter = Number(resp.headers.get("Retry-After") ?? "60");
      return {
        ok: false,
        message: `Zu viele Versuche. Bitte in ${retryAfter} s erneut probieren.`,
        retryAfter,
      };
    }
    if (resp.status === 503) {
      return { ok: false, message: "Auf dem Server ist noch kein Passwort eingerichtet." };
    }
    return { ok: false, message: `Anmeldung fehlgeschlagen (${resp.status}).` };
  } catch {
    return { ok: false, message: "Server nicht erreichbar." };
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    // Cookie läuft ohnehin ab
  }
}
