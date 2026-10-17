import { act, renderHook } from "@testing-library/react";
import { useVoice } from "./useVoice";

interface Callbacks {
  onState: (s: string) => void;
  onEvent: (e: unknown) => void;
  onError: (m: string) => void;
}

const clients: { cb: Callbacks; started: boolean; stopped: boolean }[] = [];

vi.mock("../lib/voice", async () => {
  const actual = await vi.importActual<typeof import("../lib/voice")>("../lib/voice");
  class FakeVoiceClient {
    started = false;
    stopped = false;
    constructor(public cb: Callbacks) {
      clients.push(this);
    }
    async start() {
      this.started = true;
      this.cb.onState("connecting");
    }
    resume() {}
    stop() {
      this.stopped = true;
      this.cb.onState("off");
    }
  }
  return { ...actual, VoiceClient: FakeVoiceClient };
});

async function mount(autoStart = true) {
  const hook = renderHook(() => useVoice(true, autoStart));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  return hook;
}

const last = () => clients[clients.length - 1]!;

beforeEach(() => {
  clients.length = 0;
  window.localStorage.clear();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ enabled: true, ready: true, error: null }))));
  Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn() }, configurable: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useVoice: automatisch zuhören und wieder verbinden", () => {
  it("startet von selbst, sobald die Sprache bereit ist", async () => {
    await mount();
    expect(clients).toHaveLength(1);
    expect(last().started).toBe(true);
  });

  it("startet nicht ohne autoStart", async () => {
    await mount(false);
    expect(clients).toHaveLength(0);
  });

  it("verbindet nach einem Abbruch mit wachsender Pause neu", async () => {
    await mount();
    act(() => last().cb.onError("Sprachverbindung gestört."));
    act(() => last().cb.onState("off"));
    expect(clients).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(clients).toHaveLength(2); // nach 2 s

    act(() => last().cb.onState("off"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3999);
    });
    expect(clients).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(clients).toHaveLength(3); // nach 4 s
  });

  it("setzt die Pause zurück, sobald die Verbindung wieder steht", async () => {
    await mount();
    act(() => last().cb.onState("off"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    act(() => last().cb.onState("ready"));
    act(() => last().cb.onState("off"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(clients).toHaveLength(3); // wieder 2 s statt 4 s
  });

  it("gibt nach sechs Versuchen auf", async () => {
    await mount();
    for (let i = 0; i < 8; i++) {
      act(() => last().cb.onState("off"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(31_000);
      });
    }
    expect(clients).toHaveLength(7); // 1 Start + 6 Versuche
  });

  it("versucht es nicht erneut, wenn das Mikrofon selbst nicht geht", async () => {
    await mount();
    act(() => last().cb.onError("Mikrofon nicht verfügbar oder nicht erlaubt."));
    act(() => last().cb.onState("off"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(clients).toHaveLength(1);
  });

  it("Ausschalten per Knopf bleibt aus und wird gemerkt", async () => {
    const { result, unmount } = await mount();
    act(() => result.current.toggle());
    expect(last().stopped).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(clients).toHaveLength(1);
    expect(window.localStorage.getItem("cat.mic")).toBe("off");
    unmount();
    await mount();
    expect(clients).toHaveLength(1); // kein Autostart, weil der Nutzer es ausgeschaltet hat
  });
});
