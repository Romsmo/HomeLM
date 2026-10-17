import { fireEvent, render, screen } from "@testing-library/react";
import { type CatState, initialState } from "../state/store";
import Dashboard from "./Dashboard";

const send = vi.fn();
const dispatch = vi.fn();

vi.mock("../hooks/useCat", () => ({
  useCat: () => ({ state: { ...initialState, connection: "open" } as CatState, dispatch, send }),
}));
vi.mock("../hooks/useVoice", () => ({
  useVoice: () => ({ state: "off", unavailable: "Test", latency: null, error: null, toggle: () => {} }),
}));

function setup() {
  return render(<Dashboard onUnreachable={() => {}} onLogout={() => {}} />);
}

const item = (id: string) => document.querySelector(`[data-item="${id}"]`) as HTMLElement;
const box = {
  x: 0,
  y: 0,
  left: 0,
  top: 0,
  right: 1000,
  bottom: 500,
  width: 1000,
  height: 500,
  toJSON: () => ({}),
};
const edit = () => fireEvent.click(screen.getByRole("button", { name: "Layout anpassen" }));

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

describe("Arbeitsraum: Layout anpassen", () => {
  it("zeigt Griffe nur im Anpassen-Modus", () => {
    setup();
    expect(screen.queryByRole("group", { name: /Wetter/ })).not.toBeInTheDocument();
    edit();
    expect(screen.getByRole("group", { name: /Wetter/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fertig" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Fertig" }));
    expect(screen.queryByRole("group", { name: /Wetter/ })).not.toBeInTheDocument();
  });

  it("verschiebt per Pfeiltasten, skaliert mit Umschalt und speichert das", () => {
    setup();
    edit();
    const before = item("weather").style.left;
    const group = screen.getByRole("group", { name: /Wetter/ });
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(item("weather").style.left).not.toBe(before);
    const width = item("weather").style.width;
    fireEvent.keyDown(group, { key: "ArrowRight", shiftKey: true });
    expect(item("weather").style.width).not.toBe(width);
    const saved = JSON.parse(window.localStorage.getItem("cat.layout.v1") ?? "{}");
    expect(saved.rects.weather.x).toBeCloseTo(0.78, 3);
  });

  it("lädt eine gespeicherte Anordnung", () => {
    window.localStorage.setItem(
      "cat.layout.v1",
      JSON.stringify({ rects: { weather: { x: 0.1, y: 0.2, w: 0.3, h: 0.4 } } }),
    );
    setup();
    expect(item("weather").style.left).toBe("10%");
    expect(item("weather").style.height).toBe("40%");
  });

  it("zieht per Maus und holt das Element nach vorn", () => {
    setup();
    edit();
    vi.spyOn(screen.getByLabelText("Arbeitsraum"), "getBoundingClientRect").mockReturnValue(box);
    const zBefore = Number(item("uptime").style.zIndex);
    fireEvent.pointerDown(screen.getByRole("group", { name: /Uptime/ }), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 200, clientY: 50 });
    fireEvent.pointerUp(window);
    expect(item("uptime").style.left).toBe("11%"); // 0,01 + 100/1000
    expect(item("uptime").style.top).toBe("62%"); // 0,72 - 50/500
    expect(Number(item("uptime").style.zIndex)).toBeGreaterThan(zBefore);
    expect(JSON.parse(window.localStorage.getItem("cat.layout.v1") ?? "{}").rects.uptime.x).toBeCloseTo(0.11, 3);
  });

  it("skaliert an der Ecke", () => {
    setup();
    edit();
    vi.spyOn(screen.getByLabelText("Arbeitsraum"), "getBoundingClientRect").mockReturnValue(box);
    const handle = item("system").querySelector('[data-handle="se"]') as HTMLElement;
    fireEvent.pointerDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 50, clientY: 50 });
    fireEvent.pointerUp(window);
    expect(item("system").style.width).toBe("25%"); // 0,20 + 0,05
    expect(item("system").style.height).toBe("48%"); // 0,38 + 0,10
  });

  it("blendet Elemente aus und wieder ein, Zurücksetzen stellt alles her", () => {
    setup();
    edit();
    fireEvent.click(screen.getByRole("button", { name: "Wetter ausblenden" }));
    expect(item("weather")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Wetter wieder einblenden" }));
    expect(item("weather")).not.toBeNull();
    fireEvent.keyDown(screen.getByRole("group", { name: /Wetter/ }), { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "Zurücksetzen" }));
    expect(item("weather").style.top).toBe("2%");
  });

  it("Cat selbst lässt sich nicht ausblenden", () => {
    setup();
    edit();
    expect(screen.queryByRole("button", { name: "Cat ausblenden" })).not.toBeInTheDocument();
  });

  it("öffnet beim Greifen des Kerns im Anpassen-Modus nicht den Chat", () => {
    setup();
    edit();
    fireEvent.pointerDown(screen.getByRole("group", { name: /Cat:/ }), { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(window);
    expect(screen.queryByRole("dialog", { name: "Chat mit Cat" })).not.toBeInTheDocument();
  });

  it("zeigt auf kleinen Bildschirmen die gestapelte Ansicht ohne Anpassen", () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    setup();
    expect(screen.queryByLabelText("Arbeitsraum")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Layout anpassen" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Cat wartet" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Dateien" })).toBeInTheDocument();
  });
});

describe("Arbeitsraum: Dateien ablegen", () => {
  const dropFiles = (files: File[]) => fireEvent.drop(window, { dataTransfer: { files, types: ["Files"] } });

  it("zeigt beim Ziehen die Ablagefläche", () => {
    setup();
    fireEvent.dragEnter(window, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getByTestId("drop-overlay")).toBeInTheDocument();
    fireEvent.dragLeave(window, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByTestId("drop-overlay")).not.toBeInTheDocument();
  });

  it("ignoriert Ziehen von Text", () => {
    setup();
    fireEvent.dragEnter(window, { dataTransfer: { types: ["text/plain"], files: [] } });
    expect(screen.queryByTestId("drop-overlay")).not.toBeInTheDocument();
  });

  it("lädt abgelegte Dateien hoch und zeigt den Status", async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method });
        if (init?.method === "PUT") {
          return new Response(JSON.stringify({ name: "a.txt", size: 5, kind: "text", modified: 1 }), { status: 200 });
        }
        return new Response("[]", { status: 200 });
      }),
    );
    setup();
    dropFiles([new File(["hallo"], "a b.txt", { type: "text/plain" })]);
    expect(await screen.findByText("abgelegt")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT" && c.url === "/api/files/a%20b.txt")).toBe(true);
  });

  it("meldet Fehler des Servers und lässt sie schließen", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_: string, init?: RequestInit) =>
        init?.method === "PUT"
          ? new Response(JSON.stringify({ detail: "Datei zu groß" }), { status: 413 })
          : new Response("[]", { status: 200 }),
      ),
    );
    setup();
    dropFiles([new File(["x"], "gross.bin")]);
    expect(await screen.findByText("Datei zu groß")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "gross.bin schließen" }));
    expect(screen.queryByText("Datei zu groß")).not.toBeInTheDocument();
  });

  it("lehnt leere Dateien schon im Browser ab", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    setup();
    dropFiles([new File([], "leer.txt")]);
    expect(await screen.findByText("Die Datei ist leer.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([, init]) => init?.method !== "PUT")).toBe(true);
  });

  it("listet abgelegte Dateien und zeigt, lädt, löscht sie", async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method });
        if (url === "/api/files" && !init?.method) {
          return new Response(JSON.stringify([{ name: "Foto.png", size: 2048, kind: "image", modified: 1 }]), {
            status: 200,
          });
        }
        return new Response("{}", { status: 200 });
      }),
    );
    setup();
    expect(await screen.findByText("Foto.png")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Foto.png anzeigen" }));
    expect(calls).toContainEqual({ url: "/api/files/Foto.png/show", method: "POST" });
    expect(screen.getByRole("link", { name: "Foto.png herunterladen" })).toHaveAttribute("href", "/api/files/Foto.png");
    fireEvent.click(screen.getByRole("button", { name: "Foto.png löschen" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false); // erst nachfragen
    fireEvent.click(screen.getByRole("button", { name: "Foto.png wirklich löschen" }));
    expect(calls).toContainEqual({ url: "/api/files/Foto.png", method: "DELETE" });
  });
});
