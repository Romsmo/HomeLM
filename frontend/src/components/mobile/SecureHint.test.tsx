import { render, screen, waitFor } from "@testing-library/react";
import SecureHint, { secureUrl } from "./SecureHint";

function secure(value: boolean | undefined) {
  Object.defineProperty(window, "isSecureContext", { value, configurable: true });
}

function tls(info: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok, json: async () => info })));
}

afterEach(() => {
  vi.unstubAllGlobals();
  secure(undefined);
});

describe("secureUrl", () => {
  it("behält Rechner, Pfad und Suche und wechselt auf den HTTPS-Port", () => {
    expect(secureUrl({ hostname: "192.168.0.10", pathname: "/", search: "?ui=mobile" }, 8490)).toBe(
      "https://192.168.0.10:8490/?ui=mobile",
    );
  });
});

describe("SecureHint", () => {
  it("zeigt auf einer unsicheren Seite Zertifikat und HTTPS-Link", async () => {
    secure(false);
    tls({ https: true, port: 8490, ca: true });
    render(<SecureHint />);
    const ca = await screen.findByRole("link", { name: "1. Zertifikat laden" });
    expect(ca).toHaveAttribute("href", "/api/ca.crt");
    expect(ca).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "2. HTTPS öffnen" }).getAttribute("href")).toMatch(
      /^https:\/\/[^/]+:8490\//,
    );
  });

  it("ohne CA-Datei nur der HTTPS-Link", async () => {
    secure(false);
    tls({ https: true, port: 8490, ca: false });
    render(<SecureHint />);
    expect(await screen.findByRole("link", { name: "HTTPS öffnen" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Zertifikat/ })).not.toBeInTheDocument();
  });

  it("schweigt auf einer sicheren Seite und fragt den Server gar nicht", () => {
    secure(true);
    tls({ https: true, port: 8490, ca: true });
    const { container } = render(<SecureHint />);
    expect(container).toBeEmptyDOMElement();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("schweigt, wenn der Server kein HTTPS hat oder nicht antwortet", async () => {
    secure(false);
    tls({ https: false, port: 8490, ca: false });
    const { container } = render(<SecureHint />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
