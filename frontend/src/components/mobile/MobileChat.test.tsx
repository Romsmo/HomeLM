import { fireEvent, render, screen } from "@testing-library/react";
import type { MicControl } from "../../hooks/useVoice";
import type { StageItem } from "../../protocol";
import { type CatState, initialState } from "../../state/store";
import MobileChat from "./MobileChat";

let current: CatState;
let micState: MicControl;
const send = vi.fn();
const dispatch = vi.fn();
const resume = vi.fn();
const toggle = vi.fn();

vi.mock("../../hooks/useCat", () => ({ useCat: () => ({ state: current, dispatch, send }) }));
vi.mock("../../hooks/useVoice", () => ({ useVoice: () => micState }));

const stageItem: StageItem = {
  id: "s1",
  kind: "markdown",
  title: "Einkaufsliste",
  content: "- Brot",
  chart: null,
  created_at: 1,
};

function setup(over: Partial<CatState> = {}, mic: Partial<MicControl> = {}) {
  current = { ...initialState, connection: "open", ...over };
  micState = {
    state: "ready",
    unavailable: null,
    latency: null,
    error: null,
    wakeHint: "hey cat",
    windowOpen: false,
    toggle,
    resume,
    ...mic,
  };
  const onLogout = vi.fn();
  const onDesktop = vi.fn();
  render(<MobileChat onUnreachable={() => {}} onLogout={onLogout} onDesktop={onDesktop} />);
  return { onLogout, onDesktop };
}

const msg = (id: string, role: "user" | "assistant", text: string, over = {}) => ({
  id,
  role,
  text,
  ts: 1,
  streaming: false,
  ...over,
});

beforeEach(() => {
  send.mockClear();
  dispatch.mockClear();
  resume.mockClear();
  toggle.mockClear();
  window.localStorage.clear();
});

describe("MobileChat (Handy)", () => {
  it("zeigt nur den Chat mit Verbindung, Mikrofon und Eingabe", () => {
    setup();
    expect(screen.getByRole("log", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Online");
    expect(screen.getByLabelText("Nachricht an Cat")).toBeEnabled();
    expect(screen.getByRole("button", { name: /Mikrofon ausschalten/ })).toBeInTheDocument();
    // kein Arbeitsraum, keine Widgets
    expect(screen.queryByLabelText("Arbeitsraum")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "System" })).not.toBeInTheDocument();
  });

  it("nennt im leeren Chat die Aktivierungsphrase und den Zustand des Mikrofons", () => {
    setup();
    expect(screen.getAllByText(/Sag „Hey Cat“ und deine Anfrage/).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("img", { name: "Wartet auf Sprache" }).length).toBeGreaterThan(0);
  });

  it("zeigt Verlauf, Füllsatz und die Sprachzustände", () => {
    setup(
      {
        messages: [
          msg("u", "user", "Welche Rollos sind offen?"),
          msg("a", "assistant", "", { streaming: true, filler: "Moment, ich schaue kurz nach." }),
        ],
      },
      { state: "thinking" },
    );
    expect(screen.getByText("Welche Rollos sind offen?")).toBeInTheDocument();
    expect(screen.getByText("Moment, ich schaue kurz nach.")).toBeInTheDocument();
    expect(screen.getAllByText("Ich denke nach …").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Nachricht an Cat")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Senden" })).toBeDisabled(); // Cat antwortet noch
  });

  it("sendet Nachrichten, per Knopf und per Enter, und leert das Feld", () => {
    setup();
    const field = screen.getByLabelText("Nachricht an Cat");
    fireEvent.change(field, { target: { value: "Licht an" } });
    fireEvent.click(screen.getByRole("button", { name: "Senden" }));
    expect(send).toHaveBeenCalledWith({ type: "chat.message", text: "Licht an" });
    expect(field).toHaveValue("");
    fireEvent.change(field, { target: { value: "Und Rollo auf" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(send).toHaveBeenLastCalledWith({ type: "chat.message", text: "Und Rollo auf" });
    fireEvent.change(field, { target: { value: "Zeile" } });
    fireEvent.keyDown(field, { key: "Enter", shiftKey: true });
    expect(send).toHaveBeenCalledTimes(2); // Umschalt+Enter ist ein Zeilenumbruch
  });

  it("sendet nichts ohne Verbindung und sperrt die Eingabe", () => {
    setup({ connection: "closed" });
    expect(screen.getByRole("status")).toHaveTextContent("Verbinde neu");
    expect(screen.getByLabelText("Nachricht an Cat")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Senden" })).toBeDisabled();
  });

  it("schaltet das Mikrofon per Knopf um und zeigt, warum es nicht geht", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /Mikrofon ausschalten/ }));
    expect(toggle).toHaveBeenCalled();
  });

  it("sagt, warum das Mikrofon nicht geht (z. B. ohne HTTPS)", () => {
    setup({}, { state: "off", unavailable: "Das Mikrofon geht nur mit HTTPS." });
    expect(screen.getAllByText("Das Mikrofon geht nur mit HTTPS.").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Mikrofon einschalten" })).toBeDisabled();
  });

  it("startet das Mikrofon wieder, wenn man in die App zurückkehrt", () => {
    setup();
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(resume).toHaveBeenCalled();
  });

  it("öffnet das Menü mit Leeren, Exportieren, Desktop-Ansicht und Abmelden", () => {
    const { onLogout, onDesktop } = setup({ messages: [msg("u", "user", "Hallo")] });
    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    expect(screen.getByRole("menu", { name: "Menü" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Chat leeren" }));
    expect(send).toHaveBeenCalledWith({ type: "chat.clear" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument(); // schließt nach der Wahl

    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Desktop-Ansicht" }));
    expect(onDesktop).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Abmelden" }));
    expect(onLogout).toHaveBeenCalled();
  });

  it("merkt sich, ob der Bildschirm anbleiben soll", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Menü" }));
    const toggleItem = screen.getByRole("menuitemcheckbox", { name: /Bildschirm anlassen/ });
    expect(toggleItem).toHaveAttribute("aria-checked", "true"); // Standard: an
    fireEvent.click(toggleItem);
    expect(window.localStorage.getItem("cat.keepAwake")).toBe("off");
  });

  it("macht Grafiken der Stage über einen eigenen Vollbildbereich erreichbar", () => {
    setup({ stage: [stageItem], stageIndex: 0 });
    fireEvent.click(screen.getByRole("button", { name: /Grafik oder Anzeige ansehen \(1\)/ }));
    expect(screen.getByText("Einkaufsliste")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
    expect(screen.queryByText("Einkaufsliste")).not.toBeInTheDocument();
  });

  it("fragt vor Türen und Schlössern und antwortet an den Server", () => {
    setup({
      confirm: { id: "c1", device: "tuer", command: "unlock", summary: "Soll ich die Haustür entriegeln?", expiresIn: 30, receivedAt: Date.now() },
    });
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Soll ich die Haustür entriegeln?");
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(send).toHaveBeenCalledWith({ type: "confirm.response", id: "c1", approved: false });
  });

  it("zeigt Hinweise des Servers und lässt sie schließen", () => {
    setup({ notice: "Cat antwortet noch." });
    expect(screen.getByRole("alert")).toHaveTextContent("Cat antwortet noch.");
    fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
    expect(dispatch).toHaveBeenCalledWith({ kind: "dismissNotice" });
  });
});
