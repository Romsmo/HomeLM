import { fireEvent, render, screen } from "@testing-library/react";
import type { WidgetState } from "../../state/store";
import { weatherSummary } from "./weather";
import { formatBytes, formatDuration } from "./format";
import { renderWidget } from "./renderWidget";

const widget = (over: Partial<WidgetState>): WidgetState => ({
  id: "x",
  kind: "system",
  title: "System",
  status: "ok",
  data: {},
  error: null,
  updatedAt: 100,
  refreshable: false,
  ...over,
});

const noop = () => {};

describe("format", () => {
  it("formatiert Dauer und Größe", () => {
    expect(formatDuration(42)).toBe("42 s");
    expect(formatDuration(125)).toBe("2 Min 5 s");
    expect(formatDuration(3 * 3600 + 60)).toBe("3 Std 1 Min");
    expect(formatDuration(2 * 86400 + 3 * 3600 + 4 * 60)).toBe("2 T 3 Std 4 Min");
    expect(formatBytes(512 * 1024 ** 2)).toBe("512 MB");
    expect(formatBytes(8 * 1024 ** 3)).toBe("8,0 GB");
    expect(formatBytes(223 * 1024 ** 3)).toBe("223 GB");
  });
});

describe("SystemWidget", () => {
  const data = {
    cpu_percent: 37.2,
    cpu_count: 6,
    load: [0.5, 0.4, 0.3],
    mem_total: 8 * 1024 ** 3,
    mem_used: 4 * 1024 ** 3,
    mem_percent: 50,
    disk_total: 100 * 1024 ** 3,
    disk_used: 96 * 1024 ** 3,
    disk_percent: 96,
  };

  it("zeigt Messwerte als Balken", () => {
    render(renderWidget(widget({ data }), noop));
    expect(screen.getByRole("meter", { name: "CPU" })).toHaveAttribute("aria-valuenow", "37");
    expect(screen.getByRole("meter", { name: "Arbeitsspeicher" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText(/4,0 GB \/ 8,0 GB/)).toBeInTheDocument();
    expect(screen.getByText(/Last 0,50/)).toBeInTheDocument();
  });

  it("zeigt Fehler im Widget statt zu brechen", () => {
    render(renderWidget(widget({ status: "error", error: "Systemwerte nicht lesbar" }), noop));
    expect(screen.getByRole("alert")).toHaveTextContent("Systemwerte nicht lesbar");
  });

  it("zeigt Laden ohne Daten", () => {
    render(renderWidget(widget({ status: "loading" }), noop));
    expect(screen.getByText("Lade …")).toBeInTheDocument();
  });
});

describe("UptimeWidget", () => {
  it("zeigt Server- und Cat-Laufzeit", () => {
    render(renderWidget(widget({ kind: "uptime", title: "Uptime", data: { system_seconds: 90000, cat_seconds: 61 } }), noop));
    expect(screen.getByText("1 T 1 Std 0 Min")).toBeInTheDocument();
    expect(screen.getByText("1 Min 1 s")).toBeInTheDocument();
  });
});

const weatherData = {
  name: "Berlin",
  temperature: 12.4,
  apparent: 10.1,
  humidity: 71,
  wind: 14,
  label: "Teils bewölkt",
  daily: [
    { date: "2026-10-16", tmax: 14, tmin: 7, label: "Teils bewölkt" },
    { date: "2026-10-17", tmax: 13, tmin: 6.5, label: "Leichter Regen" },
  ],
};

describe("WeatherWidget", () => {
  const base = { kind: "weather", title: "Wetter", refreshable: true, data: weatherData };

  it("zeigt aktuelles Wetter und Vorhersage", () => {
    render(renderWidget(widget(base), noop));
    expect(screen.getByText("12 °C")).toBeInTheDocument();
    expect(screen.getAllByText("Teils bewölkt").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Vorhersage").children).toHaveLength(2);
    expect(screen.getByText(/Berlin/)).toBeInTheDocument();
  });

  it("zeigt Fehler sauber, ohne Daten", () => {
    render(
      renderWidget(
        widget({ ...base, data: {}, status: "error", error: "Wetterdaten nicht erreichbar (kein Internet?)." }),
        noop,
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("kein Internet");
    expect(screen.queryByText(/°C/)).not.toBeInTheDocument();
  });

  it("behält den letzten Stand bei Fehler und weist darauf hin", () => {
    render(renderWidget(widget({ ...base, status: "error", error: "Wetterdaten nicht erreichbar." }), noop));
    expect(screen.getByRole("alert")).toHaveTextContent("letzte bekannte Stand");
    expect(screen.getByText("12 °C")).toBeInTheDocument();
  });

  it("Refresh-Knopf meldet die Widget-ID und sperrt bis zur Antwort", () => {
    const onRefresh = vi.fn();
    const { rerender } = render(<>{renderWidget(widget({ ...base, id: "weather" }), onRefresh)}</>);
    const button = screen.getByRole("button", { name: "Wetter aktualisieren" });
    fireEvent.click(button);
    expect(onRefresh).toHaveBeenCalledWith("weather");
    expect(button).toBeDisabled();
    rerender(<>{renderWidget(widget({ ...base, id: "weather", updatedAt: 200 }), onRefresh)}</>);
    expect(screen.getByRole("button", { name: "Wetter aktualisieren" })).toBeEnabled();
  });
});

describe("weatherSummary (Header)", () => {
  it("fasst das Wetter zusammen oder zeigt Platzhalter", () => {
    expect(weatherSummary(undefined)).toBe("Wetter: …");
    expect(weatherSummary(widget({ status: "loading" }))).toBe("Wetter: …");
    expect(weatherSummary(widget({ status: "error" }))).toBe("Wetter: nicht verfügbar");
    expect(weatherSummary(widget({ data: weatherData }))).toBe("12 °C, Teils bewölkt");
  });
});

describe("unbekanntes Widget", () => {
  it("zeigt Status oder Fehler", () => {
    render(renderWidget(widget({ kind: "neu", title: "Neu", status: "error", error: "kaputt" }), noop));
    expect(screen.getByText("kaputt")).toBeInTheDocument();
  });
});
