import type { MicControl } from "../../hooks/useVoice";
import type { ChatItem } from "../../state/store";
import MicButton from "../MicButton";

function titleCase(text: string): string {
  return text.replace(/(^|\s)(\p{L})/gu, (_all, space: string, letter: string) => space + letter.toUpperCase());
}

function micLine(mic: MicControl): string {
  if (mic.error) return mic.error;
  switch (mic.state) {
    case "connecting":
      return "Mikrofon verbindet …";
    case "ready":
      if (mic.windowOpen) return "Ich höre weiter zu, sprich einfach";
      return mic.wakeHint ? `Sag „${titleCase(mic.wakeHint)}“ und deine Anfrage` : "Ich höre zu, sprich einfach";
    case "listening":
      return "Ich höre …";
    case "thinking":
      return "Ich denke nach …";
    case "speaking":
      return "Cat spricht …";
    default:
      return mic.unavailable ?? "Mikrofon aus";
  }
}

/** Letzte Worte unter dem Kern (Frage und Antwort) und das Mikrofon: Cat ist immer ansprechbar. */
export default function Caption({
  messages,
  mic,
  onOpenChat,
}: {
  messages: ChatItem[];
  mic: MicControl;
  onOpenChat: () => void;
}) {
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const lastCat = [...messages].reverse().find((m) => m.role === "assistant");
  const showCat = lastCat && (!lastUser || lastCat.ts >= lastUser.ts);
  return (
    <div className="flex w-full max-w-xl shrink-0 flex-col items-center gap-2 px-2 pb-1 text-center">
      <button
        type="button"
        onClick={onOpenChat}
        aria-label="Letzte Nachrichten, Chat öffnen"
        className="block w-full cursor-pointer rounded-lg px-3 py-1.5 outline-none transition hover:bg-cyan-400/5 focus-visible:ring-2 focus-visible:ring-cyan-300"
      >
        {lastUser && <p className="line-clamp-1 text-xs text-cyan-200/50">{lastUser.text}</p>}
        <p className="hud-text-glow line-clamp-3 min-h-[1.25rem] text-sm text-cyan-50" aria-live="polite">
          {showCat ? (lastCat.text === "" && lastCat.streaming ? (lastCat.filler ?? "…") : lastCat.text) : ""}
        </p>
        {!lastUser && !lastCat && (
          <p className="text-sm text-cyan-200/60">Sprich mit Cat oder klicke auf den Kern, um zu schreiben.</p>
        )}
      </button>
      <div className="flex items-center gap-3">
        <MicButton mic={mic} className="h-11 w-11 rounded-full" />
        <p className="max-w-[16rem] text-left text-xs text-cyan-200/70" aria-live="polite">
          {micLine(mic)}
          {mic.latency && mic.state === "ready" ? ` · ${mic.latency}` : ""}
        </p>
      </div>
    </div>
  );
}
