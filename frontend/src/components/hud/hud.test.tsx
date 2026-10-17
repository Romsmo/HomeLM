import { fireEvent, render, screen } from "@testing-library/react";
import type { MicControl } from "../../hooks/useVoice";
import type { ChatItem } from "../../state/store";
import Caption from "./Caption";
import CatCore from "./CatCore";
import ChatOverlay from "./ChatOverlay";
import { Ring } from "./Hud";

const mic = (over: Partial<MicControl> = {}): MicControl => ({
  state: "off",
  unavailable: null,
  latency: null,
  error: null,
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
