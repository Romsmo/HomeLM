import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

function mockFetch(handler: (url: string) => { status: number; headers?: Record<string, string> }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const { status, headers } = handler(url);
      return new Response("{}", { status, headers });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("zeigt die Anmeldung, wenn keine Sitzung besteht", async () => {
    mockFetch(() => ({ status: 401 }));
    render(<App />);
    expect(await screen.findByLabelText("Passwort")).toBeInTheDocument();
  });

  it("zeigt bei falschem Passwort eine Meldung", async () => {
    mockFetch(() => ({ status: 401 }));
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Passwort"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Falsches Passwort");
  });

  it("nennt die Wartezeit bei Sperre", async () => {
    mockFetch((url) =>
      url === "/api/login" ? { status: 429, headers: { "Retry-After": "42" } } : { status: 401 },
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Passwort"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("42 s"));
  });

  it("bleibt im Dashboard, wenn der Server nur kurz nicht erreichbar ist", async () => {
    class DeadSocket {
      static OPEN = 1;
      readyState = 3;
      onopen = null;
      onmessage = null;
      onclose: (() => void) | null = null;
      constructor() {
        setTimeout(() => this.onclose?.(), 0);
      }
      send() {}
      close() {}
    }
    vi.stubGlobal("WebSocket", DeadSocket);
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        if (calls === 1) return new Response("{}", { status: 200 });
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<App />);
    expect(await screen.findByRole("button", { name: "Abmelden" })).toBeInTheDocument();
    await waitFor(() => expect(calls).toBeGreaterThan(1));
    expect(screen.queryByLabelText("Passwort")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abmelden" })).toBeInTheDocument();
  });

  it("geht zur Anmeldung, wenn die Sitzung abgelaufen ist", async () => {
    class DeadSocket {
      static OPEN = 1;
      readyState = 3;
      onopen = null;
      onmessage = null;
      onclose: (() => void) | null = null;
      constructor() {
        setTimeout(() => this.onclose?.(), 0);
      }
      send() {}
      close() {}
    }
    vi.stubGlobal("WebSocket", DeadSocket);
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: ++calls === 1 ? 200 : 401 })),
    );
    render(<App />);
    expect(await screen.findByLabelText("Passwort")).toBeInTheDocument();
  });
});
