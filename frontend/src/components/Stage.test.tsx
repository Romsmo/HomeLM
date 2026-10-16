import { fireEvent, render, screen } from "@testing-library/react";
import type { StageItem } from "../protocol";
import Stage from "./Stage";

vi.mock("./stage/ChartView", () => ({
  default: ({ title }: { title: string }) => <div data-testid="chart">{title}</div>,
}));

const item = (over: Partial<StageItem>): StageItem => ({
  id: "1",
  kind: "markdown",
  title: "Liste",
  content: "- Apfel\n- Birne",
  chart: null,
  created_at: 1,
  ...over,
});

function setup(items: StageItem[], index = items.length - 1) {
  const onGo = vi.fn();
  const onClear = vi.fn();
  render(<Stage voice="idle" items={items} index={index} onGo={onGo} onClear={onClear} />);
  return { onGo, onClear };
}

describe("Stage", () => {
  it("zeigt ohne Inhalt den Orb", () => {
    setup([]);
    expect(screen.getByRole("img", { name: "Cat wartet" })).toBeInTheDocument();
  });

  it("rendert Markdown formatiert", () => {
    setup([item({})]);
    expect(screen.getByText("Apfel").tagName).toBe("LI");
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
  });

  it("rendert HTML in einer Sandbox-iframe ohne allow-same-origin", () => {
    setup([item({ kind: "html", title: "Uhr", content: "<svg></svg>" })]);
    const frame = screen.getByTitle("Uhr");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("srcdoc")).toContain("Content-Security-Policy");
  });

  it("rendert Diagramme über ChartView", async () => {
    const chart = { type: "bar" as const, labels: ["a"], datasets: [{ label: "x", data: [1] }] };
    setup([item({ kind: "chart", title: "Umsatz", chart })]);
    expect(await screen.findByTestId("chart")).toHaveTextContent("Umsatz");
  });

  it("blättert in der Historie und leert", () => {
    const { onGo, onClear } = setup([item({ id: "1", title: "Erste" }), item({ id: "2", title: "Zweite" })]);
    expect(screen.getByText("Zweite")).toBeInTheDocument();
    expect(screen.getByLabelText("Nächster Stage-Inhalt")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Vorheriger Stage-Inhalt"));
    expect(onGo).toHaveBeenCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "Leeren" }));
    expect(onClear).toHaveBeenCalled();
  });
});
