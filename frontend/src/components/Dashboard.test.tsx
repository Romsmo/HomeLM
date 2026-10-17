import { fireEvent, render, screen } from "@testing-library/react";
import type { StageItem } from "../protocol";
import { type CatState, initialState } from "../state/store";
import Dashboard from "./Dashboard";

let current: CatState;
const send = vi.fn();
const dispatch = vi.fn();

vi.mock("../hooks/useCat", () => ({ useCat: () => ({ state: current, dispatch, send }) }));
vi.mock("../hooks/useVoice", () => ({
  useVoice: () => ({ state: "off", unavailable: "Test", latency: null, error: null, toggle: () => {} }),
}));

const stageItem: StageItem = {
  id: "s1",
  kind: "markdown",
  title: "Einkaufsliste",
  content: "- Brot",
  chart: null,
  created_at: 1,
};

function setup(over: Partial<CatState> = {}) {
  current = { ...initialState, connection: "open", ...over };
  return render(<Dashboard onUnreachable={() => {}} onLogout={() => {}} />);
}

beforeEach(() => {
  send.mockClear();
  dispatch.mockClear();
});

describe("Dashboard (Arbeitsraum)", () => {
  it("zeigt Cat in der Mitte und die Widgets ringsum, ohne Chat", () => {
    setup();
    expect(screen.getByRole("img", { name: "Cat wartet" })).toBeInTheDocument();
    expect(screen.getByLabelText("Widgets links")).toBeInTheDocument();
    expect(screen.getByLabelText("Widgets rechts")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Chat mit Cat" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stage")).not.toBeInTheDocument();
  });

  it("öffnet den Chat per Klick auf den Kern und schließt ihn mit Escape", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Chat öffnen" }));
    expect(screen.getByRole("dialog", { name: "Chat mit Cat" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Chat mit Cat" })).not.toBeInTheDocument();
  });

  it("sendet Chat-Nachrichten aus dem Overlay", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Chat öffnen" }));
    const input = screen.getByLabelText("Nachricht an Cat");
    fireEvent.change(input, { target: { value: "Licht an" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(send).toHaveBeenCalledWith({ type: "chat.message", text: "Licht an" });
  });

  it("legt die Stage über den Kern und blendet sie aus, ohne zu löschen", () => {
    setup({ stage: [stageItem], stageIndex: 0 });
    expect(screen.getByLabelText("Stage")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ausblenden" }));
    expect(screen.queryByLabelText("Stage")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cat wartet" })).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it("leert die Stage auf Wunsch", () => {
    setup({ stage: [stageItem], stageIndex: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Leeren" }));
    expect(send).toHaveBeenCalledWith({ type: "stage.clear" });
  });

  it("zeigt die letzte Antwort unter dem Kern und Platzhalter für fehlende Widgets", () => {
    setup({
      messages: [
        { id: "1", role: "user", text: "Wie warm ist es?", ts: 1, streaming: false },
        { id: "2", role: "assistant", text: "Zwölf Grad.", ts: 2, streaming: false },
      ],
    });
    expect(screen.getByText("Zwölf Grad.")).toBeInTheDocument();
    expect(screen.getAllByText("Warte auf Daten …").length).toBeGreaterThanOrEqual(2);
  });

  it("zeigt den Sprachzustand im Kern", () => {
    setup({ voice: "speaking" });
    expect(screen.getByRole("img", { name: "Cat spricht" })).toBeInTheDocument();
  });

  it("zeigt Hinweise und lässt sie schließen", () => {
    setup({ notice: "Etwas ist passiert" });
    expect(screen.getByRole("alert")).toHaveTextContent("Etwas ist passiert");
    fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
    expect(dispatch).toHaveBeenCalledWith({ kind: "dismissNotice" });
  });
});
