import { fireEvent, render, screen } from "@testing-library/react";
import type { MicControl } from "../../hooks/useVoice";
import type { ChatItem } from "../../state/store";
import type { Brain } from "../../hooks/useBrain";
import Caption from "./Caption";
import CatCore from "./CatCore";
import ChatOverlay from "./ChatOverlay";
import { Ring } from "./Hud";
import LearnedPanel from "./LearnedPanel";

const mic = (over: Partial<MicControl> = {}): MicControl => ({
  state: "off",
  unavailable: null,
  latency: null,
  error: null,
  wakeHint: null,
  windowOpen: false,
  toggle: () => {},
  ...over,
});

const msg = (over: Partial<ChatItem>): ChatItem => ({
  id: "1",
  role: "user",
  text: "Hallo",
  ts: 1,
  streaming: false,
  ...over,
});

describe("CatCore", () => {
  it("zeigt den Zustand und öffnet beim Klick den Chat", () => {
    const onOpen = vi.fn();
    render(<CatCore state="listening" onOpen={onOpen} />);
    expect(screen.getByRole("img", { name: "Cat hört zu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Chat öffnen" }));
    expect(onOpen).toHaveBeenCalled();
  });

  it("ist ohne Handler nur Anzeige", () => {
    render(<CatCore state="idle" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cat wartet" })).toBeInTheDocument();
  });

  it("trägt den Zustand als Attribut für die Animation", () => {
    const { container } = render(<CatCore state="thinking" />);
    expect(container.querySelector(".core")).toHaveAttribute("data-state", "thinking");
  });
});

describe("Ring", () => {
  it("zeigt den Wert als Messgerät und färbt hohe Werte", () => {
    const { container, rerender } = render(<Ring label="CPU" percent={37.4} />);
    const meter = screen.getByRole("meter", { name: "CPU" });
    expect(meter).toHaveAttribute("aria-valuenow", "37");
    expect(screen.getByText("37 %")).toBeInTheDocument();
    expect(container.querySelector(".ring-arc")).toHaveAttribute("stroke", "#22e5ff");
    rerender(<Ring label="CPU" percent={97} />);
    expect(container.querySelector(".ring-arc")).toHaveAttribute("stroke", "#f43f5e");
    rerender(<Ring label="CPU" percent={null} />);
    expect(screen.getByText("–")).toBeInTheDocument();
  });
});

describe("Caption", () => {
  it("zeigt Frage und Antwort und öffnet den Chat", () => {
    const onOpenChat = vi.fn();
    render(
      <Caption
        messages={[msg({ text: "Wie spät ist es?" }), msg({ id: "2", role: "assistant", text: "Es ist drei.", ts: 2 })]}
        mic={mic()}
        onOpenChat={onOpenChat}
      />,
    );
    expect(screen.getByText("Wie spät ist es?")).toBeInTheDocument();
    expect(screen.getByText("Es ist drei.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Chat öffnen/ }));
    expect(onOpenChat).toHaveBeenCalled();
  });

  it("zeigt anfangs einen Hinweis und nennt den Mikrofon-Zustand", () => {
    const { rerender } = render(
      <Caption messages={[]} mic={mic({ unavailable: "Nur mit HTTPS." })} onOpenChat={() => {}} />,
    );
    expect(screen.getByText(/klicke auf den Kern/)).toBeInTheDocument();
    expect(screen.getByText("Nur mit HTTPS.")).toBeInTheDocument();
    rerender(<Caption messages={[]} mic={mic({ state: "ready" })} onOpenChat={() => {}} />);
    expect(screen.getByText(/sprich einfach/)).toBeInTheDocument();
  });

  it("nennt die Aktivierungsphrase und zeigt das offene Gesprächsfenster", () => {
    const { rerender } = render(
      <Caption messages={[]} mic={mic({ state: "ready", wakeHint: "hey cat" })} onOpenChat={() => {}} />,
    );
    expect(screen.getByText(/Sag „Hey Cat“ und deine Anfrage/)).toBeInTheDocument();
    rerender(
      <Caption
        messages={[]}
        mic={mic({ state: "ready", wakeHint: "hey cat", windowOpen: true })}
        onOpenChat={() => {}}
      />,
    );
    expect(screen.getByText(/Ich höre weiter zu/)).toBeInTheDocument();
  });
});

describe("ChatOverlay", () => {
  const props = { messages: [], connected: true, busy: false, onSend: () => {}, onClear: () => {} };

  it("schließt mit Escape, Knopf und Klick auf den Hintergrund", () => {
    const onClose = vi.fn();
    const { container } = render(<ChatOverlay onClose={onClose} {...props} />);
    expect(screen.getByRole("dialog", { name: "Chat mit Cat" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Chat schließen" }));
    fireEvent.mouseDown(container.firstElementChild as Element);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("schließt nicht bei Klick in den Chat", () => {
    const onClose = vi.fn();
    render(<ChatOverlay onClose={onClose} {...props} />);
    fireEvent.mouseDown(screen.getByLabelText("Nachricht an Cat"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("LearnedPanel mit Gedächtnis", () => {
  const brain = (over: Partial<Brain> = {}): Brain => ({
    notes: [
      { path: "vorlieben/kaffee.md", topic: "vorlieben", title: "Kaffee", date: "2026-10-19", tags: ["auto"], text: "Der Nutzer trinkt Kaffee." },
    ],
    people: {
      enabled: true,
      voiceAvailable: true,
      people: [{ id: "p1", name: "Roman", created: 1, last_seen: null, voice: true, samples: 3 }],
    },
    terms: [{ term: "Dachrollos", devices: ["Romans Rollo", "Marius Rollo"], uses: 1 }],
    fillers: [{ text: "Moment, ich schaue kurz nach.", category: "lookup", source: "generated", uses: 2, last_used: null }],
    error: null,
    removeNote: vi.fn(),
    removeVoice: vi.fn(),
    removePerson: vi.fn(),
    removeFiller: vi.fn(),
    removeTerm: vi.fn(),
    ...over,
  });
  const panel = (b: Brain) => (
    <LearnedPanel rows={[]} error={null} needed={2} onForget={() => {}} onForgetAll={() => {}} brain={b} />
  );

  it("wechselt zwischen Notizen, Personen und Füllsätzen", () => {
    render(panel(brain()));
    fireEvent.click(screen.getByRole("tab", { name: "Notizen" }));
    expect(screen.getByText("Kaffee")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Personen" }));
    expect(screen.getByText("Roman")).toBeInTheDocument();
    expect(screen.getByText(/Stimme gespeichert \(3\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Füllsätze" }));
    expect(screen.getByText("Moment, ich schaue kurz nach.")).toBeInTheDocument();
    expect(screen.getByText(/dazugelernt/)).toBeInTheDocument();
  });

  it("zeigt erklärte Begriffe mit ihren Geräten und löscht sie einzeln", () => {
    const b = brain();
    render(panel(b));
    fireEvent.click(screen.getByRole("tab", { name: "Begriffe" }));
    expect(screen.getByText("Dachrollos")).toBeInTheDocument();
    expect(screen.getByText(/Romans Rollo, Marius Rollo/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Begriff „Dachrollos“ vergessen" }));
    fireEvent.click(screen.getByRole("button", { name: "Begriff „Dachrollos“ wirklich vergessen" }));
    expect(b.removeTerm).toHaveBeenCalledWith("Dachrollos");
  });

  it("löscht erst nach einer zweiten Bestätigung", () => {
    const b = brain();
    render(panel(b));
    fireEvent.click(screen.getByRole("tab", { name: "Notizen" }));
    const button = screen.getByRole("button", { name: "Notiz „Kaffee“ vergessen" });
    fireEvent.click(button);
    expect(b.removeNote).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Notiz „Kaffee“ wirklich vergessen" }));
    expect(b.removeNote).toHaveBeenCalledWith("vorlieben/kaffee.md");
  });

  it("vergisst nur die Stimme oder die ganze Person", () => {
    const b = brain();
    render(panel(b));
    fireEvent.click(screen.getByRole("tab", { name: "Personen" }));
    fireEvent.click(screen.getByRole("button", { name: "Stimme von Roman vergessen" }));
    fireEvent.click(screen.getByRole("button", { name: "Stimme von Roman wirklich vergessen" }));
    expect(b.removeVoice).toHaveBeenCalledWith("p1");
    expect(b.removePerson).not.toHaveBeenCalled();
  });

  it("sagt, wenn noch nichts da ist", () => {
    render(panel(brain({ notes: [], fillers: [], people: { enabled: true, voiceAvailable: false, people: [] } })));
    fireEvent.click(screen.getByRole("tab", { name: "Notizen" }));
    expect(screen.getByText(/Noch keine Notizen/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Personen" }));
    expect(screen.getByText(/Ich kenne noch niemanden/)).toBeInTheDocument();
  });
});
