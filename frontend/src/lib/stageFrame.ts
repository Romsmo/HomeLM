/** Strikte Content-Security-Policy für KI-erzeugtes HTML: kein Netzwerk, nur Inline-Inhalte. */
export const STAGE_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  "img-src data:",
  "font-src data:",
  "media-src data:",
  "connect-src 'none'",
  "frame-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join("; ");

const BASE_STYLE =
  "html,body{margin:0;height:100%;background:#020617;color:#e2e8f0;font-family:system-ui,sans-serif}svg{display:block}";

/** Baut das Dokument für die Sandbox-iframe. Die CSP steht vor jedem Inhalt der KI. */
export function buildSrcDoc(html: string): string {
  return (
    `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${STAGE_CSP}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<style>${BASE_STYLE}</style></head><body>${html}</body></html>`
  );
}

export type FrameMessage = { type: "cat.ready" };

/** Feste postMessage-Schnittstelle: nur diese Nachricht wird angenommen, alles andere verworfen. */
export function parseFrameMessage(data: unknown): FrameMessage | null {
  if (typeof data !== "object" || data === null) return null;
  const record = data as Record<string, unknown>;
  const keys = Object.keys(record);
  if (record.type === "cat.ready" && keys.length === 1) return { type: "cat.ready" };
  return null;
}
