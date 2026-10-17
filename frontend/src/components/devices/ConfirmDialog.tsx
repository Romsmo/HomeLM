import { useEffect, useRef, useState } from "react";
import type { PendingConfirm } from "../../state/store";

export default function ConfirmDialog({
  confirm,
  onAnswer,
}: {
  confirm: PendingConfirm;
  onAnswer: (approved: boolean) => void;
}) {
  const [left, setLeft] = useState(confirm.expiresIn);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const answerRef = useRef(onAnswer);
  answerRef.current = onAnswer;

  useEffect(() => {
    setLeft(confirm.expiresIn);
    const id = setInterval(() => {
      setLeft(Math.max(0, confirm.expiresIn - Math.floor((Date.now() - confirm.receivedAt) / 1000)));
    }, 500);
    return () => clearInterval(id);
  }, [confirm]);

  // Sicherer Standard: Fokus auf "Abbrechen", Escape lehnt ab, Ablauf schließt den Dialog.
  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") answerRef.current(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (left === 0) answerRef.current(false);
  }, [left]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-sm rounded-2xl border border-amber-500/60 bg-slate-900 p-5 shadow-2xl"
      >
        <h2 id="confirm-title" className="text-base font-semibold text-amber-300">
          Bestätigung nötig
        </h2>
        <p className="mt-2 text-slate-100">{confirm.summary}</p>
        <p className="mt-1 text-xs text-slate-400">Läuft in {left} s ab, dann passiert nichts.</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={() => onAnswer(false)}
            className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-100 hover:border-slate-400"
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={() => onAnswer(true)}
            className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400"
          >
            Ja, ausführen
          </button>
        </div>
      </div>
    </div>
  );
}
