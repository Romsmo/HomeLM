import type { ServerEvent } from "../protocol";
import { type CatState, initialState, reducer } from "./store";

const apply = (state: CatState, event: ServerEvent) => reducer(state, { kind: "server", event });

describe("reducer", () => {
  it("baut eine gestreamte Antwort aus Delta-Teilen auf", () => {
    let s = apply(initialState, { type: "chat.message", id: "a", role: "assistant", text: "", ts: 1 });
    expect(s.messages[0]?.streaming).toBe(true);
    s = apply(s, { type: "chat.delta", id: "a", delta: "Hal" });
    s = apply(s, { type: "chat.delta", id: "a", delta: "lo" });
    s = apply(s, { type: "chat.done", id: "a" });
    expect(s.messages[0]).toMatchObject({ text: "Hallo", streaming: false });
  });

  it("zeigt einen Füllsatz nur, solange die Antwort noch leer ist", () => {
    let s = apply(initialState, { type: "chat.message", id: "a", role: "assistant", text: "", ts: 1 });
    s = apply(s, { type: "chat.filler", id: "a", text: "Moment, ich schaue kurz nach." });
    expect(s.messages[0]?.filler).toBe("Moment, ich schaue kurz nach.");
    s = apply(s, { type: "chat.delta", id: "a", delta: "Offen." });
    s = apply(s, { type: "chat.filler", id: "a", text: "Noch ein Satz." });
    expect(s.messages[0]).toMatchObject({ text: "Offen.", filler: "Moment, ich schaue kurz nach." });
  });

  it("ersetzt doppelt gesendete Nachrichten statt sie zu verdoppeln", () => {
    const event: ServerEvent = { type: "chat.message", id: "u", role: "user", text: "x", ts: 1 };
    const s = apply(apply(initialState, event), event);
    expect(s.messages).toHaveLength(1);
  });

  it("entfernt eine leere Antwort bei chat.done (Fehlerfall)", () => {
    let s = apply(initialState, { type: "chat.message", id: "a", role: "assistant", text: "", ts: 1 });
    s = apply(s, { type: "chat.done", id: "a" });
    expect(s.messages).toHaveLength(0);
  });

  it("verwirft den lokalen Stand, wenn die Verbindung (neu) offen ist", () => {
    let s = apply(initialState, { type: "chat.message", id: "u", role: "user", text: "x", ts: 1 });
    s = reducer(s, { kind: "connection", status: "closed" });
    expect(s.messages).toHaveLength(1);
    s = reducer(s, { kind: "connection", status: "open" });
    expect(s.messages).toHaveLength(0);
    expect(s.connection).toBe("open");
  });

  it("zeigt Servermeldungen an und schließt sie wieder", () => {
    let s = apply(initialState, { type: "error", message: "Mist" });
    expect(s.notice).toBe("Mist");
    s = reducer(s, { kind: "dismissNotice" });
    expect(s.notice).toBeNull();
  });

  it("chat.clear leert den Verlauf", () => {
    let s = apply(initialState, { type: "chat.message", id: "u", role: "user", text: "x", ts: 1 });
    s = apply(s, { type: "chat.clear" });
    expect(s.messages).toHaveLength(0);
  });
});
