import { render, screen } from "@testing-library/react";
import Header, { shortModel } from "./Header";

describe("Header: antwortendes Modell", () => {
  it("kürzt Modellnamen", () => {
    expect(shortModel("anthropic/claude-haiku-5-5")).toBe("claude-haiku-5-5");
    expect(shortModel("ollama/qwen3:4b")).toBe("qwen3:4b");
    expect(shortModel("lokal")).toBe("lokal");
  });

  it("zeigt das Cloud-Modell unauffällig", () => {
    render(
      <Header connection="open" weather={undefined} provider={{ name: "anthropic/claude-haiku-5-5", offline: false }} onLogout={() => {}} />,
    );
    expect(screen.getByTestId("provider-badge")).toHaveTextContent("Modell: claude-haiku-5-5");
    expect(screen.getByTestId("provider-badge").className).not.toContain("amber");
  });

  it("hebt das Offline-Modell hervor", () => {
    render(
      <Header connection="open" weather={undefined} provider={{ name: "ollama/qwen3:4b", offline: true }} onLogout={() => {}} />,
    );
    const badge = screen.getByTestId("provider-badge");
    expect(badge).toHaveTextContent("Offline-Modell: qwen3:4b");
    expect(badge.className).toContain("amber");
  });

  it("zeigt nichts, solange der Server noch kein Modell gemeldet hat", () => {
    render(<Header connection="open" weather={undefined} provider={null} onLogout={() => {}} />);
    expect(screen.queryByTestId("provider-badge")).not.toBeInTheDocument();
  });
});
