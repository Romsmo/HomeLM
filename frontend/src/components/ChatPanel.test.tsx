import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import type { ChatItem } from "../state/store";
import type { MicControl } from "../hooks/useVoice";
import ChatPanel from "./ChatPanel";

const msg = (over: Partial<ChatItem>): ChatItem => ({
  id: "1",
  role: "user",
  text: "Hallo",
  ts: 1,
  streaming: false,
  ...over,
});

function setup(props: Partial<ComponentProps<typeof ChatPanel>> = {}) {
  const onSend = vi.fn();
  const onClear = vi.fn();
  render(<ChatPanel messages={[]} connected busy={false} onSend={onSend} onClear={onClear} {...props} />);
  return { onSend, onClear };
}

describe("ChatPanel", () => {
  it("sendet mit Enter und leert das Feld", () => {
    const { onSend } = setup();
    const input = screen.getByLabelText("Nachricht an Cat");
    fireEvent.change(input, { target: { value: "  Licht an  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Licht an");
    expect(input).toHaveValue("");
  });

  it("Shift+Enter sendet nicht", () => {
    const { onSend } = setup();
    const input = screen.getByLabelText("Nachricht an Cat");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("sperrt die Eingabe ohne Verbindung", () => {
    setup({ connected: false });
    expect(screen.getByLabelText("Nachricht an Cat")).toBeDisabled();
  });

  it("zeigt Nachrichten und ruft Leeren auf", () => {
    const { onClear } = setup({
      messages: [msg({ text: "Frage" }), msg({ id: "2", role: "assistant", text: "**Antwort**" })],
    });
    expect(screen.getByText("Frage")).toBeInTheDocument();
    expect(screen.getByText("Antwort").tagName).toBe("STRONG");
    fireEvent.click(screen.getByRole("button", { name: "Leeren" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("deaktiviert Senden, solange Cat antwortet", () => {
    setup({ busy: true });
    fireEvent.change(screen.getByLabelText("Nachricht an Cat"), { target: { value: "x" } });
    expect(screen.getByRole("button", { name: "Senden" })).toBeDisabled();
  });

  describe("Mikrofon", () => {
    const mic = (over: Partial<MicControl> = {}): MicControl => ({
      state: "off",
      unavailable: null,
      latency: null,
      error: null,
      toggle: vi.fn(),
      ...over,
    });

    it("schaltet das Mikrofon per Knopf", () => {
      const control = mic();
      setup({ mic: control });
      fireEvent.click(screen.getByRole("button", { name: "Mikrofon einschalten" }));
      expect(control.toggle).toHaveBeenCalled();
    });

    it("ist gesperrt und erklärt warum, wenn das Mikrofon nicht nutzbar ist", () => {
      setup({ mic: mic({ unavailable: "Das Mikrofon braucht HTTPS oder localhost." }) });
      const button = screen.getByRole("button", { name: "Mikrofon einschalten" });
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("title", "Das Mikrofon braucht HTTPS oder localhost.");
    });

    it("bleibt bedienbar, solange es läuft, auch wenn der Status später kippt", () => {
      setup({ mic: mic({ state: "listening", unavailable: "egal" }) });
      const button = screen.getByRole("button", { name: /Mikrofon ausschalten/ });
      expect(button).toBeEnabled();
      expect(button).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("Ich höre zu …")).toBeInTheDocument();
    });

    it("zeigt Latenz und Fehler an", () => {
      setup({ mic: mic({ state: "ready", latency: "Antwort nach 0,5 s" }) });
      expect(screen.getByText("Antwort nach 0,5 s")).toBeInTheDocument();
    });

    it("zeigt den Fehler vor allem anderen", () => {
      setup({ mic: mic({ state: "off", error: "Mikrofon nicht verfügbar oder nicht erlaubt." }) });
      expect(screen.getByText("Mikrofon nicht verfügbar oder nicht erlaubt.")).toBeInTheDocument();
    });

    it("zeigt ohne Sprachfunktion gar keinen Knopf", () => {
      setup({});
      expect(screen.queryByRole("button", { name: /Mikrofon/ })).not.toBeInTheDocument();
    });
  });
});
