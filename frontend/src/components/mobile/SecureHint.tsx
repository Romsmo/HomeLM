import { useEffect, useState } from "react";

interface TlsInfo {
  https: boolean;
  port: number;
  ca: boolean;
}

/** Adresse der sicheren Variante derselben Seite: gleicher Rechner, HTTPS-Port von Cat. */
export function secureUrl(loc: Pick<Location, "hostname" | "pathname" | "search">, port: number): string {
  return `https://${loc.hostname}:${port}${loc.pathname}${loc.search}`;
}

/**
 * Das Mikrofon geht im Browser nur über HTTPS. Auf einer unsicheren Seite (http://192.168.0.10:8090)
 * zeigt das zwei Schritte: das Zertifikat der Heimnetz-CA laden und installieren (einmal je Gerät),
 * dann dieselbe Seite über HTTPS öffnen (docs/https.md). Auf einer sicheren Seite erscheint nichts.
 */
export default function SecureHint() {
  const insecure = typeof window !== "undefined" && window.isSecureContext === false;
  const [info, setInfo] = useState<TlsInfo | null>(null);

  useEffect(() => {
    if (!insecure) return;
    let alive = true;
    fetch("/api/tls", { credentials: "same-origin" })
      .then((r) => (r.ok ? (r.json() as Promise<TlsInfo>) : null))
      .then((data) => {
        if (alive) setInfo(data);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [insecure]);

  if (!insecure || !info?.https) return null;

  const link =
    "flex min-h-11 flex-1 items-center justify-center rounded-xl border border-cyan-400/40 bg-cyan-400/10 px-3 text-center text-sm text-cyan-50 active:bg-cyan-400/20";
  return (
    <section
      aria-label="Sichere Verbindung für das Mikrofon"
      className="mx-3 mb-1 rounded-xl border border-amber-400/30 bg-amber-950/40 p-3 text-sm text-amber-100"
    >
      <p>Das Mikrofon geht nur über HTTPS. Diese Seite ist nicht gesichert.</p>
      <div className="mt-2 flex gap-2">
        {info.ca && (
          <a href="/api/ca.crt" download className={link}>
            1. Zertifikat laden
          </a>
        )}
        <a href={secureUrl(window.location, info.port)} className={link}>
          {info.ca ? "2. HTTPS öffnen" : "HTTPS öffnen"}
        </a>
      </div>
      {info.ca && (
        <p className="mt-2 text-xs text-amber-200/70">
          Das Zertifikat einmal installieren (Einstellungen, Sicherheit, Zertifikat installieren, CA-Zertifikat;
          iPhone: Profil laden und unter Info, Zertifikatsvertrauenseinstellungen aktivieren).
        </p>
      )}
    </section>
  );
}
