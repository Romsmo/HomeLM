import { useState } from "react";
import type { LearnedRow } from "../../lib/learned";
import { HudPanel } from "./Hud";

/** Was Cat aus Wiederholungen gelernt hat: Kurzbefehle, die ohne Sprachmodell sofort laufen. */
export default function LearnedPanel({
  rows,
  error,
  needed,
  onForget,
  onForgetAll,
}: {
  rows: LearnedRow[];
  error: string | null;
  needed: number;
  onForget: (id: string) => void;
  onForgetAll: () => void;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const ask = (key: string, act: () => void) => {
    if (confirming === key) {
      setConfirming(null);
      act();
    } else {
      setConfirming(key);
      setTimeout(() => setConfirming((c) => (c === key ? null : c)), 3000);
    }
  };
  const anyActive = rows.some((r) => r.active);
  return (
    <HudPanel
      title="Gelernt"
      action={
        anyActive ? (
          <button
            type="button"
            onClick={() => ask("*", onForgetAll)}
            className={`hud-btn rounded-md px-2 py-0.5 text-xs ${confirming === "*" ? "!border-rose-400 text-rose-300" : ""}`}
          >
            {confirming === "*" ? "Sicher?" : "Alles vergessen"}
          </button>
        ) : undefined
      }
    >
      {error && (
        <p role="alert" className="mb-1 text-xs text-rose-400">
          {error}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-sm text-cyan-200/50">
          Noch nichts. Löse ich dieselbe Anfrage {needed}-mal gleich, merke ich sie mir und antworte künftig sofort.
        </p>
      ) : (
        <ul className="grid gap-1.5 text-sm" aria-label="Gelernte Kurzbefehle">
          {rows.map((r) => (
            <li key={r.id} className="flex items-start gap-2">
              <span
                aria-hidden
                className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${r.active ? "bg-cyan-300 shadow-[0_0_6px_var(--hud)]" : "bg-cyan-900"}`}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-cyan-100/90" title={r.phrase}>
                  „{r.phrase}“
                </div>
                <div className="truncate text-[0.7rem] text-cyan-200/50" title={r.does}>
                  {r.does}
                  {r.active ? ` · ${r.uses}× genutzt` : ` · gesehen ${r.seen}/${r.needed}`}
                </div>
              </div>
              <button
                type="button"
                aria-label={confirming === r.id ? `„${r.phrase}“ wirklich vergessen` : `„${r.phrase}“ vergessen`}
                onClick={() => ask(r.id, () => onForget(r.id))}
                className={`shrink-0 rounded border px-1.5 text-xs ${
                  confirming === r.id
                    ? "border-rose-400 text-rose-300"
                    : "border-cyan-400/20 text-cyan-200/60 hover:border-rose-400 hover:text-rose-300"
                }`}
              >
                {confirming === r.id ? "Sicher?" : "×"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </HudPanel>
  );
}
