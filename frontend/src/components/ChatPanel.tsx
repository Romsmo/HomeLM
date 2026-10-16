import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { chatToMarkdown, downloadText, exportFileName } from "../lib/exportChat";
import type { ChatItem } from "../state/store";

function Bubble({ message }: { message: ChatItem }) {
  const mine = message.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
          mine
            ? "bg-cyan-500/90 text-slate-950"
            : message.role === "system"
              ? "bg-slate-800 text-slate-300 italic"
              : "border border-slate-700 bg-slate-900 text-slate-100"
        }`}
      >
        {mine ? (
          <p className="whitespace-pre-wrap">{message.text}</p>
        ) : message.text === "" && message.streaming ? (
          <span className="text-slate-400" aria-label="Cat schreibt">
            …
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
}: {
  messages: ChatItem[];
  connected: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  onClear: () => void;
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
      className="flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur"
    >
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-xs font-semibold tracking-widest text-slate-400 uppercase">Chat</h2>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => downloadText(exportFileName(), chatToMarkdown(messages))}
            disabled={messages.length === 0}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-slate-300 transition hover:border-slate-500 disabled:opacity-40"
          >
            Exportieren
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={messages.length === 0 || busy}
            className="rounded-md border border-slate-700 px-2.5 py-1 text-slate-300 transition hover:border-rose-500 hover:text-rose-300 disabled:opacity-40"
          >
            Leeren
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="m-auto text-center text-sm text-slate-500">Sag etwas zu Cat.</p>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} message={m} />
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="flex items-end gap-2 border-t border-slate-800 p-3">
        <textarea
          aria-label="Nachricht an Cat"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={4000}
          placeholder={connected ? "Nachricht an Cat …" : "Keine Verbindung …"}
          disabled={!connected}
          className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-400 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!connected || busy || draft.trim() === ""}
          className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40"
        >
          Senden
        </button>
      </form>
    </section>
  );
}
