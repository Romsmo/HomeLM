import { STAGE_CSP, buildSrcDoc, parseFrameMessage } from "./stageFrame";

describe("buildSrcDoc", () => {
  it("setzt die CSP vor den Inhalt der KI", () => {
    const doc = buildSrcDoc("<script>alert(1)</script>");
    expect(doc.indexOf("Content-Security-Policy")).toBeGreaterThan(-1);
    expect(doc.indexOf("Content-Security-Policy")).toBeLessThan(doc.indexOf("alert(1)"));
    expect(doc.startsWith("<!doctype html>")).toBe(true);
  });

  it("verbietet Netzwerk, fremde Skripte, Frames und Formulare", () => {
    expect(STAGE_CSP).toContain("default-src 'none'");
    expect(STAGE_CSP).toContain("connect-src 'none'");
    expect(STAGE_CSP).toContain("frame-src 'none'");
    expect(STAGE_CSP).toContain("form-action 'none'");
    expect(STAGE_CSP).toContain("img-src data:");
    expect(STAGE_CSP).not.toMatch(/https?:/);
    expect(STAGE_CSP).not.toContain("*");
  });
});

describe("parseFrameMessage", () => {
  it("akzeptiert nur die feste Ready-Nachricht", () => {
    expect(parseFrameMessage({ type: "cat.ready" })).toEqual({ type: "cat.ready" });
  });

  it.each([
    null,
    "cat.ready",
    42,
    {},
    { type: "cat.send", text: "Haustür öffnen" },
    { type: "cat.ready", extra: "x" },
    { type: ["cat.ready"] },
  ])("verwirft %j", (data) => {
    expect(parseFrameMessage(data)).toBeNull();
  });
});
