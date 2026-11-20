import { renderHook, act } from "@testing-library/react";
import { detectUi, useUiMode } from "./useUiMode";

describe("detectUi", () => {
  it("nimmt zuerst die Adresse, dann die gemerkte Wahl, dann die Bildschirmgröße", () => {
    expect(detectUi("?ui=mobile", "desktop", false)).toBe("mobile");
    expect(detectUi("?ui=desktop", "mobile", true)).toBe("desktop");
    expect(detectUi("", "desktop", true)).toBe("desktop");
    expect(detectUi("", "mobile", false)).toBe("mobile");
    expect(detectUi("", null, true)).toBe("mobile");
    expect(detectUi("", null, false)).toBe("desktop");
  });

  it("ignoriert unbrauchbare Werte", () => {
    expect(detectUi("?ui=quatsch", "auch-quatsch", true)).toBe("mobile");
    expect(detectUi("?ui=quatsch", null, false)).toBe("desktop");
  });
});

describe("useUiMode", () => {
  const phone = (matches: boolean) =>
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches, addEventListener: () => {}, removeEventListener: () => {} })),
    );

  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("wählt auf einem schmalen Bildschirm die Handy-Ansicht", () => {
    phone(true);
    const { result } = renderHook(() => useUiMode());
    expect(result.current[0]).toBe("mobile");
  });

  it("bleibt auf einem breiten Bildschirm beim Arbeitsraum", () => {
    phone(false);
    const { result } = renderHook(() => useUiMode());
    expect(result.current[0]).toBe("desktop");
  });

  it("merkt sich ?ui=mobile und nimmt es aus der Adresse, wenn man wechselt", () => {
    phone(false);
    window.history.replaceState(null, "", "/?ui=mobile");
    const { result } = renderHook(() => useUiMode());
    expect(result.current[0]).toBe("mobile");
    expect(window.localStorage.getItem("cat.ui")).toBe("mobile");
    act(() => result.current[1]("desktop"));
    expect(result.current[0]).toBe("desktop");
    expect(window.localStorage.getItem("cat.ui")).toBe("desktop");
    expect(window.location.search).toBe("");
  });

  it("kehrt mit auto zur Bildschirmgröße zurück", () => {
    phone(true);
    window.localStorage.setItem("cat.ui", "desktop");
    const { result } = renderHook(() => useUiMode());
    expect(result.current[0]).toBe("desktop");
    act(() => result.current[1]("auto"));
    expect(result.current[0]).toBe("mobile");
    expect(window.localStorage.getItem("cat.ui")).toBeNull();
  });
});
