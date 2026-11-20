import type { ReactNode } from "react";

function Item({
  onClick,
  disabled,
  children,
  danger,
  checked,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
  danger?: boolean;
  checked?: boolean;
}) {
  return (
    <button
      type="button"
      role={checked === undefined ? "menuitem" : "menuitemcheckbox"}
      aria-checked={checked}
      onClick={onClick}
      disabled={disabled}
      className={`flex min-h-12 w-full items-center px-4 text-left text-base disabled:opacity-40 ${
        danger ? "text-rose-300" : "text-cyan-50"
      } active:bg-cyan-400/10`}
    >
      {children}
    </button>
  );
}

/** Menü oben rechts: Chat leeren oder sichern, Bildschirm anlassen, Ansicht wechseln, Abmelden. */
export default function MobileMenu({
  open,
  onToggle,
  onClose,
  hasMessages,
  busy,
  stageCount,
  keepAwake,
  onClear,
  onExport,
  onStage,
  onKeepAwake,
  onDesktop,
  onLogout,
}: {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  hasMessages: boolean;
  busy: boolean;
  stageCount: number;
  keepAwake: boolean;
  onClear: () => void;
  onExport: () => void;
  onStage: () => void;
  onKeepAwake: (on: boolean) => void;
  onDesktop: () => void;
  onLogout: () => void;
}) {
  const run = (act: () => void) => () => {
    onClose();
    act();
  };
  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Menü"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onToggle}
        className="grid h-11 w-11 place-items-center rounded-full border border-cyan-400/30 text-cyan-100 active:bg-cyan-400/10"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <circle cx="12" cy="5" r="1.8" />
          <circle cx="12" cy="12" r="1.8" />
          <circle cx="12" cy="19" r="1.8" />
        </svg>
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-label="Menü schließen"
            tabIndex={-1}
            onClick={onClose}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div
            role="menu"
            aria-label="Menü"
            className="absolute right-0 z-40 mt-2 w-64 overflow-hidden rounded-2xl border border-cyan-400/30 bg-slate-950/95 py-1 shadow-2xl backdrop-blur"
          >
            {stageCount > 0 && <Item onClick={run(onStage)}>Grafik ansehen ({stageCount})</Item>}
            <Item onClick={run(onExport)} disabled={!hasMessages}>
              Chat exportieren
            </Item>
            <Item onClick={run(onClear)} disabled={!hasMessages || busy} danger>
              Chat leeren
            </Item>
            <Item onClick={() => onKeepAwake(!keepAwake)} checked={keepAwake}>
              <span className="flex-1">Bildschirm anlassen</span>
              <span
                aria-hidden
                className={`h-6 w-10 rounded-full p-0.5 transition ${keepAwake ? "bg-cyan-400" : "bg-slate-700"}`}
              >
                <span className={`block h-5 w-5 rounded-full bg-white transition ${keepAwake ? "translate-x-4" : ""}`} />
              </span>
            </Item>
            <Item onClick={run(onDesktop)}>Desktop-Ansicht</Item>
            <Item onClick={run(onLogout)}>Abmelden</Item>
          </div>
        </>
      )}
    </div>
  );
}
