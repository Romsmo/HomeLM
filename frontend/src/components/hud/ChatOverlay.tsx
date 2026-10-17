import { type ComponentProps, useEffect } from "react";
import ChatPanel from "../ChatPanel";

/**
 * Chat als Fläche über dem Arbeitsraum. Schließen mit Escape, Klick auf den Hintergrund oder dem Knopf.
 * Der Arbeitsraum dahinter bleibt sichtbar, Cat hört weiter zu.
 */
export default function ChatOverlay({
  onClose,
  ...chat
}: { onClose: () => void } & ComponentProps<typeof ChatPanel>) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="hud-backdrop fixed inset-0 z-40 grid place-items-center p-3 sm:p-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-label="Chat mit Cat"
        className="hud-in chat-overlay relative flex h-[min(88dvh,48rem)] w-full max-w-2xl flex-col"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Chat schließen"
          title="Chat schließen (Esc)"
          className="hud-btn absolute -top-3 -right-3 z-10 grid h-8 w-8 place-items-center rounded-full bg-black/80"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M2 2l8 8M10 2 2 10" />
          </svg>
        </button>
        <ChatPanel {...chat} />
      </div>
    </div>
  );
}
