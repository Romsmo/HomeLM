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
const bar = (name: RegExp) => screen.getByRole("group", { name });
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
const stored = () => JSON.parse(window.localStorage.getItem("cat.layout.v1") ?? "{}");

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

describe("Arbeitsraum: Fenster-Bedienung ohne Bearbeiten-Knopf", () => {
  it("hat keinen Anpassen-Schalter, die Griffe sind immer da", () => {
    setup();
    expect(screen.queryByRole("button", { name: /Layout anpassen|Fertig/ })).not.toBeInTheDocument();
    for (const name of ["Wetter", "System", "Uptime", "Geräte", "Dateien", "Datum", "Uhr", "Stage"].slice(0, 7)) {
      expect(bar(new RegExp(`^${name}:`))).toBeInTheDocument();
    }
    expect(item("weather").querySelector('[data-handle="se"]')).not.toBeNull();
  });

  it("Cat sitzt fest in der Mitte: keine Griffe, nicht verschiebbar", () => {
    setup();
    expect(screen.queryByRole("group", { name: /^Cat:/ })).not.toBeInTheDocument();
    expect(item("core").querySelector("[data-handle]")).toBeNull();
    expect(item("core").style.left).toBe("26%");
    expect(item("core").style.width).toBe("48%"); // 26 % + 48 % + 26 % = mittig
  });

  it("ein gespeicherter Platz für Cat wird ignoriert", () => {
    window.localStorage.setItem(
      "cat.layout.v1",
      JSON.stringify({ rects: { core: { x: 0, y: 0, w: 0.2, h: 0.2 }, weather: { x: 0.1, y: 0.2, w: 0.3, h: 0.4 } } }),
    );
    setup();
    expect(item("core").style.left).toBe("26%");
    expect(item("weather").style.left).toBe("10%");
    expect(item("weather").style.height).toBe("40%");
  });

  it("verschiebt per Pfeiltasten, skaliert mit Umschalt und speichert das", () => {
    setup();
    const before = item("weather").style.left;
    const width = item("weather").style.width;
    fireEvent.keyDown(bar(/^Wetter:/), { key: "ArrowLeft" });
    expect(item("weather").style.left).not.toBe(before);
    fireEvent.keyDown(bar(/^Wetter:/), { key: "ArrowLeft", shiftKey: true });
    expect(item("weather").style.width).not.toBe(width);
    expect(stored().rects.weather.x).toBeCloseTo(0.78, 3);
  });

  it("verschiebt per Maus am Balken oben und holt das Element nach vorn", () => {
    setup();
    vi.spyOn(screen.getByLabelText("Arbeitsraum"), "getBoundingClientRect").mockReturnValue(box);
    const zBefore = Number(item("uptime").style.zIndex);
    fireEvent.pointerDown(bar(/^Uptime:/), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 200, clientY: 50 });
    fireEvent.pointerUp(window);
    expect(item("uptime").style.left).toBe("11%"); // 0,01 + 100/1000
    expect(item("uptime").style.top).toBe("62%"); // 0,72 - 50/500
    expect(Number(item("uptime").style.zIndex)).toBeGreaterThan(zBefore);
    expect(stored().rects.uptime.x).toBeCloseTo(0.11, 3);
  });

  it("skaliert wie ein Fenster an der Ecke unten rechts", () => {
    setup();
    vi.spyOn(screen.getByLabelText("Arbeitsraum"), "getBoundingClientRect").mockReturnValue(box);
    const grip = item("system").querySelector('[data-handle="se"]') as HTMLElement;
    fireEvent.pointerDown(grip, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 50, clientY: 50 });
    fireEvent.pointerUp(window);
    expect(item("system").style.left).toBe("1%"); // die linke obere Ecke bleibt stehen
    expect(item("system").style.top).toBe("32%");
    expect(item("system").style.width).toBe("25%"); // 0,20 + 0,05
    expect(item("system").style.height).toBe("48%"); // 0,38 + 0,10
  });

  it("der Inhalt bleibt bedienbar (Schaltflächen im Widget funktionieren ohne Modus)", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Panel öffnen" }));
    expect(dispatch).toHaveBeenCalledWith({ kind: "showDevices" });
  });

  it("blendet Elemente aus und wieder ein, Zurücksetzen stellt alles her", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Wetter ausblenden" }));
    expect(item("weather")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Wetter wieder einblenden" }));
    expect(item("weather")).not.toBeNull();
    fireEvent.keyDown(bar(/^Wetter:/), { key: "ArrowDown" });
    expect(item("weather").style.top).not.toBe("2%");
    fireEvent.click(screen.getByRole("button", { name: "Layout zurücksetzen" }));
    expect(item("weather").style.top).toBe("2%");
  });

  it("Cat und Sprache lassen sich nicht ausblenden", () => {
    setup();
    expect(screen.queryByRole("button", { name: /^(Cat|Sprache) ausblenden$/ })).not.toBeInTheDocument();
  });

  it("zeigt auf kleinen Bildschirmen die gestapelte Ansicht ohne Griffe", () => {
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    setup();
    expect(screen.queryByLabelText("Arbeitsraum")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Wetter:/ })).not.toBeInTheDocument();
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


describe("Arbeitsraum: Gelerntes", () => {
  const row = (over: Record<string, unknown> = {}) => ({
    id: "abc123",
    phrase: "schalte {dev} an",
    does: "{Gerät} (senden: on)",
    active: true,
    seen: 2,
    needed: 2,
    uses: 5,
    ...over,
  });

  it("erklärt, wie Cat lernt, solange noch nichts gelernt ist", async () => {
    setup();
    expect(await screen.findByText(/merke ich sie mir und antworte künftig sofort/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Gelernt" })).toBeInTheDocument();
  });

  it("zeigt Gelerntes mit Nutzung und Fortschritt und vergisst es nach Rückfrage", async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method });
        if (url === "/api/learned" && !init?.method) {
          return new Response(JSON.stringify([row(), row({ id: "z9", phrase: "gute nacht", active: false, seen: 1, uses: 0 })]));
        }
        return new Response("[]");
      }),
    );
    setup();
    expect(await screen.findByText("„schalte {dev} an“")).toBeInTheDocument();
    expect(screen.getByText(/5× genutzt/)).toBeInTheDocument();
    expect(screen.getByText(/gesehen 1\/2/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "„schalte {dev} an“ vergessen" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false); // erst nachfragen
    fireEvent.click(screen.getByRole("button", { name: "„schalte {dev} an“ wirklich vergessen" }));
    expect(calls).toContainEqual({ url: "/api/learned/abc123", method: "DELETE" });
  });

  it("vergisst auf Wunsch alles auf einmal", async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method });
        return new Response(url === "/api/learned" && !init?.method ? JSON.stringify([row()]) : "[]");
      }),
    );
    setup();
    await screen.findByText("„schalte {dev} an“");
    fireEvent.click(screen.getByRole("button", { name: "Alles vergessen" }));
    fireEvent.click(screen.getByRole("button", { name: "Sicher?" }));
    expect(calls).toContainEqual({ url: "/api/learned", method: "DELETE" });
  });

  it("meldet einen Fehler beim Vergessen", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === "DELETE") return new Response(JSON.stringify({ detail: "Das gibt es nicht (mehr)." }), { status: 404 });
        return new Response(url === "/api/learned" ? JSON.stringify([row()]) : "[]");
      }),
    );
    setup();
    await screen.findByText("„schalte {dev} an“");
    fireEvent.click(screen.getByRole("button", { name: "„schalte {dev} an“ vergessen" }));
    fireEvent.click(screen.getByRole("button", { name: "„schalte {dev} an“ wirklich vergessen" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Das gibt es nicht (mehr).");
  });
});
