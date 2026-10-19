import { useState } from "react";
import type { Brain } from "../../hooks/useBrain";
import type { LearnedRow } from "../../lib/learned";
import { HudPanel } from "./Hud";

type Tab = "learned" | "notes" | "people" | "fillers";

const TABS: { id: Tab; label: string }[] = [
  { id: "learned", label: "Kurzbefehle" },
  { id: "notes", label: "Notizen" },
  { id: "people", label: "Personen" },
  { id: "fillers", label: "Füllsätze" },
];

const CATEGORY_LABEL: Record<string, string> = {
  lookup: "Nachsehen",
  control: "Schalten",
  memory: "Merken",
  think: "Nachdenken",
  claude: "Claude",
};

function formatDay(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleDateString("de-DE") : "noch nie";
}

/** Zweistufiges Löschen: erster Klick fragt "Sicher?", der zweite löscht. */
function useConfirm() {
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
  return { confirming, ask };
}

function ForgetButton({
  label,
  active,
  onClick,
  text = "×",
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  text?: string;
}) {
  return (
    <button
      type="button"
      aria-label={active ? `${label} wirklich vergessen` : `${label} vergessen`}
      onClick={onClick}
      className={`shrink-0 rounded border px-1.5 text-xs ${
        active
          ? "border-rose-400 text-rose-300"
          : "border-cyan-400/20 text-cyan-200/60 hover:border-rose-400 hover:text-rose-300"
      }`}
    >
      {active ? "Sicher?" : text}
    </button>
  );
}

function Row({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-300 shadow-[0_0_6px_var(--hud)]" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-cyan-100/90" title={title}>
          {title}
        </div>
        <div className="truncate text-[0.7rem] text-cyan-200/50" title={sub}>
          {sub}
        </div>
      </div>
      {children}
    </li>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-cyan-200/50">{children}</p>;
}

/**
 * Was Cat gelernt hat: kurze Befehle (ohne Sprachmodell), Notizen im Gedächtnis, bekannte Personen
 * und Füllsätze. Alles lässt sich einzeln vergessen.
 */
export default function LearnedPanel({
  rows,
  error,
  needed,
  onForget,
  onForgetAll,
  brain,
}: {
  rows: LearnedRow[];
  error: string | null;
  needed: number;
  onForget: (id: string) => void;
  onForgetAll: () => void;
  brain?: Brain;
}) {
  const [tab, setTab] = useState<Tab>("learned");
  const { confirming, ask } = useConfirm();
  const anyActive = rows.some((r) => r.active);
  const shownError = error ?? brain?.error ?? null;
  return (
    <HudPanel
      title="Gelernt"
      action={
        tab === "learned" && anyActive ? (
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
      {brain && (
        <div role="tablist" aria-label="Gelerntes" className="mb-1.5 flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`rounded px-1.5 py-0.5 text-[0.7rem] ${
                tab === t.id ? "bg-cyan-400/15 text-cyan-100" : "text-cyan-200/55 hover:text-cyan-100"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
      {shownError && (
        <p role="alert" className="mb-1 text-xs text-rose-400">
          {shownError}
        </p>
      )}
      {tab === "learned" &&
        (rows.length === 0 ? (
          <Empty>
            Noch nichts. Löse ich dieselbe Anfrage {needed}-mal gleich, merke ich sie mir und antworte künftig sofort.
          </Empty>
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
                <ForgetButton
                  label={`„${r.phrase}“`}
                  active={confirming === r.id}
                  onClick={() => ask(r.id, () => onForget(r.id))}
                />
              </li>
            ))}
          </ul>
        ))}
      {brain && tab === "notes" &&
        (brain.notes.length === 0 ? (
          <Empty>Noch keine Notizen. Sag „Merk dir, dass …“, oder ich merke mir Dauerhaftes von selbst.</Empty>
        ) : (
          <ul className="grid gap-1.5 text-sm" aria-label="Notizen im Gedächtnis">
            {brain.notes.map((n) => (
              <Row key={n.path} title={n.title} sub={`${n.topic} · ${n.date || "ohne Datum"} · ${n.text}`}>
                <ForgetButton
                  label={`Notiz „${n.title}“`}
                  active={confirming === n.path}
                  onClick={() => ask(n.path, () => brain.removeNote(n.path))}
                />
              </Row>
            ))}
          </ul>
        ))}
      {brain && tab === "people" &&
        (brain.people.people.length === 0 ? (
          <Empty>
            Ich kenne noch niemanden.
            {brain.people.enabled
              ? " Ich frage nach dem Namen, oder sag „Ich heiße …“."
              : " Das Kennenlernen ist ausgeschaltet."}
          </Empty>
        ) : (
          <ul className="grid gap-1.5 text-sm" aria-label="Bekannte Personen">
            {brain.people.people.map((p) => (
              <Row
                key={p.id}
                title={p.name}
                sub={`${p.voice ? `Stimme gespeichert (${p.samples})` : "ohne Stimme"} · zuletzt ${formatDay(p.last_seen)}`}
              >
                {p.voice && (
                  <ForgetButton
                    label={`Stimme von ${p.name}`}
                    text="Stimme ×"
                    active={confirming === `v${p.id}`}
                    onClick={() => ask(`v${p.id}`, () => brain.removeVoice(p.id))}
                  />
                )}
                <ForgetButton
                  label={p.name}
                  active={confirming === p.id}
                  onClick={() => ask(p.id, () => brain.removePerson(p.id))}
                />
              </Row>
            ))}
          </ul>
        ))}
      {brain && tab === "fillers" &&
        (brain.fillers.length === 0 ? (
          <Empty>Keine Füllsätze.</Empty>
        ) : (
          <ul className="grid gap-1.5 text-sm" aria-label="Füllsätze">
            {brain.fillers.map((f) => (
              <Row
                key={f.text}
                title={f.text}
                sub={`${CATEGORY_LABEL[f.category] ?? f.category} · ${f.source === "generated" ? "dazugelernt" : "Vorgabe"} · ${f.uses}× genutzt`}
              >
                <ForgetButton
                  label={`Füllsatz „${f.text}“`}
                  active={confirming === f.text}
                  onClick={() => ask(f.text, () => brain.removeFiller(f.text))}
                />
              </Row>
            ))}
          </ul>
        ))}
    </HudPanel>
  );
}
