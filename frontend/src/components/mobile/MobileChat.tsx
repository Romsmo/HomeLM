import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useCat } from "../../hooks/useCat";
import { keepAwakePreferred, rememberKeepAwake, useViewportHeight, useWakeLock } from "../../hooks/usePhone";
import { useVoice } from "../../hooks/useVoice";
import { chatToMarkdown, downloadText, exportFileName } from "../../lib/exportChat";
import type { ConnectionStatus } from "../../lib/socket";
import { micStatusText } from "../../lib/micText";
import { Bubble } from "../ChatPanel";
import MicButton from "../MicButton";
import Stage from "../Stage";
import ConfirmDialog from "../devices/ConfirmDialog";
import MobileMenu from "./MobileMenu";
import VoiceOrb from "./VoiceOrb";

const STATUS: Record<ConnectionStatus, { label: string; dot: string }> = {
  open: { label: "Online", dot: "bg-emerald-400" },
  connecting: { label: "Verbinde …", dot: "bg-amber-400 animate-pulse" },
  closed: { label: "Verbinde neu …", dot: "bg-rose-500 animate-pulse" },
};

/**
 * Handy-Oberfläche: nur ein Chat. Das Mikrofon hört von selbst zu (außer es wurde ausgeschaltet;
 * das merkt sich der Browser), kommt man in die App zurück, geht es wieder an. Die Eingabezeile
 * bleibt über der Tastatur, alles respektiert Notch und Gestenleiste.
 */
export default function MobileChat({
  onUnreachable,
  onLogout,
  onDesktop,
}: {
  onUnreachable: () => void;
  onLogout: () => void;
  onDesktop: () => void;
}) {
  const { state, dispatch, send } = useCat(onUnreachable);
  const connected = state.connection === "open";
  const busy = state.messages.some((m) => m.streaming);
  const mic = useVoice(connected, true);
  const height = useViewportHeight();
  const [keepAwake, setKeepAwake] = useState(keepAwakePreferred);
  useWakeLock(keepAwake && mic.state !== "off");
  const [menuOpen, setMenuOpen] = useState(false);
  const [stageOpen, setStageOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);

  // Neue Nachricht oder neue Höhe (Tastatur): ans Ende scrollen.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [state.messages, height]);

  // Eingabefeld wächst mit dem Text (bis fünf Zeilen).
  useEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  }, [draft]);

  // Zurück in der App (Bildschirm wieder an, Tab gewechselt): Mikrofon wieder starten.
  const { resume } = mic;
  useEffect(() => {
    const onBack = () => {
      if (document.visibilityState === "visible") resume?.();
    };
    document.addEventListener("visibilitychange", onBack);
    window.addEventListener("pageshow", onBack);
    return () => {
      document.removeEventListener("visibilitychange", onBack);
      window.removeEventListener("pageshow", onBack);
    };
  }, [resume]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || !connected || busy) return;
    send({ type: "chat.message", text });
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  const status = STATUS[state.connection];
  const orbMode = mic.state === "off" ? "off" : mic.state;
  return (
    <div
      className="hud-bg fixed inset-x-0 top-0 flex flex-col overflow-hidden"
      style={{ height: `${height}px` }}
    >
      <header className="flex items-center justify-between gap-2 border-b border-cyan-400/20 bg-black/60 px-3 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] backdrop-blur">
        <div className="flex min-w-0 items-center gap-2">
          <h1 className="hud-text-glow text-lg font-semibold tracking-[0.25em] text-cyan-300 uppercase">Cat</h1>
          <span role="status" className="flex items-center gap-1.5 text-xs text-slate-300">
            <span className={`inline-block h-2 w-2 rounded-full ${status.dot}`} aria-hidden />
            {status.label}
          </span>
        </div>
        <MobileMenu
          open={menuOpen}
          onToggle={() => setMenuOpen((o) => !o)}
          onClose={() => setMenuOpen(false)}
          hasMessages={state.messages.length > 0}
          busy={busy}
          stageCount={state.stage.length}
          keepAwake={keepAwake}
          onClear={() => send({ type: "chat.clear" })}
          onExport={() => downloadText(exportFileName(), chatToMarkdown(state.messages))}
          onStage={() => setStageOpen(true)}
          onKeepAwake={(on) => {
            setKeepAwake(on);
            rememberKeepAwake(on);
          }}
          onDesktop={onDesktop}
          onLogout={onLogout}
        />
      </header>

      {state.notice && (
        <div role="alert" className="flex items-center justify-between gap-3 bg-rose-950/80 px-3 py-2 text-sm text-rose-200">
          <span>{state.notice}</span>
          <button
            type="button"
            onClick={() => dispatch({ kind: "dismissNotice" })}
            className="min-h-11 px-2 underline"
          >
            Schließen
          </button>
        </div>
      )}

      <div
        role="log"
        aria-live="polite"
        aria-label="Chat"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain px-3 py-3"
      >
        {state.messages.length === 0 && (
          <div className="m-auto flex flex-col items-center gap-3 text-center">
            <VoiceOrb mode={orbMode} large />
            <p aria-live="polite" className="max-w-[16rem] text-sm text-cyan-200/60">{micStatusText(mic)}</p>
          </div>
        )}
        {state.messages.map((m) => (
          <Bubble key={m.id} message={m} className="text-base" />
        ))}
        <div ref={endRef} />
      </div>

      {state.stage.length > 0 && (
        <button
          type="button"
          onClick={() => setStageOpen(true)}
          className="mx-3 mb-1 min-h-11 rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-3 text-sm text-cyan-100"
        >
          Grafik oder Anzeige ansehen ({state.stage.length})
        </button>
      )}

      {/* Im leeren Chat zeigt die große Kugel den Status schon; die Zeile erst mit Verlauf. */}
      {state.messages.length > 0 && (
        <div
          aria-live="polite"
          className="flex items-center gap-2.5 border-t border-cyan-400/15 bg-black/40 px-3 py-1.5 text-xs text-cyan-200/80"
        >
          <VoiceOrb mode={orbMode} />
          <span className="min-w-0 flex-1 truncate">{micStatusText(mic)}</span>
        </div>
      )}

      <form
        onSubmit={submit}
        className="flex items-end gap-2 border-t border-cyan-400/20 bg-black/60 px-2.5 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]"
      >
        <MicButton mic={mic} className="h-12 w-12 rounded-full" />
        <textarea
          ref={field}
          aria-label="Nachricht an Cat"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={4000}
          enterKeyHint="send"
          autoComplete="off"
          autoCorrect="on"
          placeholder={connected ? "Nachricht an Cat …" : "Keine Verbindung …"}
          disabled={!connected}
          className="max-h-32 min-h-12 flex-1 resize-none rounded-2xl border border-cyan-400/25 bg-black/50 px-3.5 py-3 text-base leading-snug outline-none focus:border-cyan-300 disabled:opacity-50"
        />
        <button
          type="submit"
          aria-label="Senden"
          disabled={!connected || busy || draft.trim() === ""}
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-cyan-300 text-slate-950 transition active:scale-95 disabled:opacity-40"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden>
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      </form>

      {stageOpen && state.stage.length > 0 && (
        <div className="hud-bg fixed inset-0 z-40 flex flex-col pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
          <div className="flex justify-end p-2">
            <button
              type="button"
              onClick={() => setStageOpen(false)}
              className="min-h-11 rounded-xl border border-cyan-400/30 px-4 text-sm text-cyan-100"
            >
              Schließen
            </button>
          </div>
          <div className="min-h-0 flex-1 px-2 pb-2">
            <Stage
              items={state.stage}
              index={state.stageIndex}
              onGo={(index) => dispatch({ kind: "stageGo", index })}
              onClear={() => {
                send({ type: "stage.clear" });
                setStageOpen(false);
              }}
              onHide={() => setStageOpen(false)}
              devices={state.devices}
              control={state.control}
              deviceError={state.deviceError}
              onDeviceCommand={(id, command) => send({ type: "device.command", id, command })}
            />
          </div>
        </div>
      )}

      {state.confirm && (
        <ConfirmDialog
          confirm={state.confirm}
          onAnswer={(approved) => {
            send({ type: "confirm.response", id: state.confirm?.id ?? "", approved });
            dispatch({ kind: "confirmClose" });
          }}
        />
      )}
    </div>
  );
}
