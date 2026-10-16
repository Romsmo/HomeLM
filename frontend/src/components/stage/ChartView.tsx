import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PieController,
  PointElement,
  Tooltip,
} from "chart.js";
import { useEffect, useRef } from "react";
import type { ChartSpec } from "../../protocol";

// Nur die benötigten Teile registrieren (kleineres Bundle).
Chart.register(
  BarController,
  LineController,
  PieController,
  DoughnutController,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  Tooltip,
  Legend,
);

const PALETTE = ["#22d3ee", "#818cf8", "#34d399", "#fbbf24", "#f472b6", "#fb923c", "#a78bfa", "#94a3b8"];
const TEXT = "#cbd5e1";
const GRID = "rgba(148, 163, 184, 0.15)";

export function buildChartConfig(spec: ChartSpec) {
  const radial = spec.type === "pie" || spec.type === "doughnut";
  const datasets = spec.datasets.map((ds, i) => {
    const color = PALETTE[i % PALETTE.length] ?? "#22d3ee";
    return {
      label: ds.label,
      data: ds.data,
      backgroundColor: radial
        ? spec.labels.map((_, j) => PALETTE[j % PALETTE.length] ?? color)
        : spec.type === "line"
          ? `${color}33`
          : color,
      borderColor: radial ? "#0f172a" : color,
      borderWidth: 2,
      tension: 0.3,
      fill: false,
    };
  });
  return {
    type: spec.type,
    data: { labels: spec.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: { legend: { labels: { color: TEXT } } },
      ...(radial
        ? {}
        : {
            scales: {
              x: {
                ticks: { color: TEXT },
                grid: { color: GRID },
                title: { display: !!spec.x_label, text: spec.x_label ?? "", color: TEXT },
              },
              y: {
                ticks: { color: TEXT },
                grid: { color: GRID },
                title: { display: !!spec.y_label, text: spec.y_label ?? "", color: TEXT },
              },
            },
          }),
    },
  } as const;
}

export default function ChartView({ spec, title }: { spec: ChartSpec; title: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const chart = new Chart(el, buildChartConfig(spec) as never);
    return () => chart.destroy();
  }, [spec]);

  return (
    <div className="h-full w-full p-4">
      <canvas ref={canvas} role="img" aria-label={`Diagramm: ${title}`} />
    </div>
  );
}
