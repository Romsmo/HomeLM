import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatToMarkdown, downloadText, exportFileName } from "../lib/exportChat";
import type { MicControl } from "../hooks/useVoice";
import MicButton from "./MicButton";
import type { ChatItem } from "../state/store";

function Bubble({ message }: { message: ChatItem }) {
  const mine = message.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
          mine
            ? "bg-cyan-300/90 text-slate-950"
            : message.role === "system"
              ? "bg-slate-800 text-slate-300 italic"
              : "border border-cyan-400/25 bg-black/40 text-cyan-50"
        }`}
      >
        {mine ? (
          <p className="whitespace-pre-wrap">{message.text}</p>
        ) : message.text === "" && message.streaming ? (
          <span className="text-slate-400" aria-label="Cat schreibt">
            {message.filler ?? "…"}
          </span>
        ) : (
          <div className="prose-cat">
            <Markdown remarkPlugins={[remarkGfm]}>{message.text}</Markdown>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPanel({
  messages,
  connected,
  busy,
  onSend,
  onClear,
  mic,
}: {
  messages: ChatItem[];
  connected: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  onClear: () => void;
  mic?: MicControl;
}) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || !connected || busy) return;
    onSend(text);
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <section
      aria-label="Chat"
      className="hud-panel hud-solid flex min-h-0 flex-1 flex-col"
    >
      <header className="flex items-center justify-between border-b border-cyan-400/15 px-4 py-2.5">
        <h2 className="hud-title">Chat</h2>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => downloadText(exportFileName(), chatToMarkdown(messages))}
            disabled={messages.length === 0}
            className="hud-btn rounded-md px-2.5 py-1 disabled:opacity-40"
          >
            Exportieren
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={messages.length === 0 || busy}
            className="hud-btn rounded-md px-2.5 py-1 hover:!border-rose-500 hover:!text-rose-300 disabled:opacity-40"
          >
            Leeren
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="m-auto text-center text-sm text-cyan-200/40">Sag etwas zu Cat.</p>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>

      {mic && (mic.latency || mic.error || (mic.state !== "off" && mic.state !== "ready")) && (
        <p className="border-t border-cyan-400/15 px-4 py-1.5 text-xs text-cyan-200/70" aria-live="polite">
          {mic.error
            ? mic.error
            : mic.state === "listening"
              ? "Ich höre zu …"
              : mic.state === "thinking"
                ? "Ich denke nach …"
                : mic.state === "speaking"
                  ? "Cat spricht …"
                  : mic.latency}
        </p>
      )}
      <form onSubmit={submit} className="flex items-end gap-2 border-t border-cyan-400/15 p-3">
        {mic && <MicButton mic={mic} />}
        <textarea
          aria-label="Nachricht an Cat"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={4000}
          autoFocus
          placeholder={connected ? "Nachricht an Cat …" : "Keine Verbindung …"}
          disabled={!connected}
          className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-cyan-400/25 bg-black/50 px-3 py-2 text-sm outline-none focus:border-cyan-300 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!connected || busy || draft.trim() === ""}
          className="rounded-xl bg-cyan-300 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-200 disabled:opacity-40"
        >
          Senden
        </button>
      </form>
    </section>
  );
}
