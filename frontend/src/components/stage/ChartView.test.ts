import type { ChartSpec } from "../../protocol";
import { buildChartConfig } from "./ChartView";

const bar: ChartSpec = {
  type: "bar",
  labels: ["Jan", "Feb"],
  datasets: [
    { label: "A", data: [1, 2] },
    { label: "B", data: [3, 4] },
  ],
  y_label: "Euro",
};

describe("buildChartConfig", () => {
  it("übernimmt Typ, Labels und Datensätze mit eigenen Farben", () => {
    const cfg = buildChartConfig(bar);
    expect(cfg.type).toBe("bar");
    expect(cfg.data.labels).toEqual(["Jan", "Feb"]);
    expect(cfg.data.datasets.map((d) => d.data)).toEqual([[1, 2], [3, 4]]);
    expect(cfg.data.datasets[0]?.backgroundColor).not.toBe(cfg.data.datasets[1]?.backgroundColor);
  });

  it("zeigt Achsentitel nur, wenn angegeben", () => {
    const cfg = buildChartConfig(bar);
    expect(cfg.options).toHaveProperty("scales.y.title.display", true);
    expect(cfg.options).toHaveProperty("scales.x.title.display", false);
  });

  it("nutzt für Torte eine Farbe je Segment und keine Achsen", () => {
    const cfg = buildChartConfig({ type: "pie", labels: ["a", "b", "c"], datasets: [{ label: "x", data: [1, 2, 3] }] });
    expect(cfg.options).not.toHaveProperty("scales");
    const colors = cfg.data.datasets[0]?.backgroundColor as string[];
    expect(new Set(colors).size).toBe(3);
  });
});
