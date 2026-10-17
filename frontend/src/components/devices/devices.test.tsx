import { act, fireEvent, render, screen } from "@testing-library/react";
import type { DeviceInfo } from "../../protocol";
import { type PendingConfirm, initialState, reducer } from "../../state/store";
import ConfirmDialog from "./ConfirmDialog";
import DevicePanel from "./DevicePanel";
import { controlNote, displayState, groupByRoom, isOn, nextSetpoint } from "./deviceUtils";

const dev = (over: Partial<DeviceInfo>): DeviceInfo => ({
  id: "licht",
  name: "Wohnzimmer Licht",
  room: "Wohnzimmer",
  type: "light",
  risk: "low",
  state: "OFF",
  unit: null,
  online: true,
  controllable: true,
  test: false,
  ...over,
});

describe("deviceUtils", () => {
  it("erkennt An-Zustände und formatiert Anzeigen", () => {
    expect(isOn(dev({ state: "ON" }))).toBe(true);
    expect(isOn(dev({ state: "OFF" }))).toBe(false);
    expect(isOn(dev({ type: "dimmer", state: "40" }))).toBe(true);
    expect(isOn(dev({ type: "dimmer", state: "0" }))).toBe(false);
    expect(displayState(dev({ state: "ON" }))).toBe("an");
    expect(displayState(dev({ type: "thermostat", state: "21.5", unit: "°C" }))).toBe("21,5 °C");
    expect(displayState(dev({ type: "dimmer", state: "75" }))).toBe("75 %");
    expect(displayState(dev({ type: "lock", state: "locked" }))).toBe("verriegelt");
    expect(displayState(dev({ type: "shutter", state: "0" }))).toBe("offen");
    expect(displayState(dev({ type: "shutter", state: "100" }))).toBe("zu");
    expect(displayState(dev({ type: "shutter", state: "30" }))).toBe("30 % zu");
    expect(displayState(dev({ state: null }))).toBe("unbekannt");
    expect(displayState(dev({ online: false }))).toBe("offline");
  });

  it("gruppiert nach Raum und filtert", () => {
    const list = [dev({ id: "a" }), dev({ id: "b", room: "Küche" }), dev({ id: "c" })];
    expect(groupByRoom(list, "").map(([r, d]) => [r, d.length])).toEqual([
      ["Küche", 1],
      ["Wohnzimmer", 2],
    ]);
    expect(groupByRoom(list, "küche")).toHaveLength(1);
    expect(groupByRoom(list, "Keller")).toHaveLength(0);
  });

  it("begrenzt Thermostat-Schritte auf 5 bis 30 Grad", () => {
    expect(nextSetpoint(dev({ type: "thermostat", state: "21" }), 0.5)).toBe(21.5);
    expect(nextSetpoint(dev({ type: "thermostat", state: "30" }), 0.5)).toBe(30);
    expect(nextSetpoint(dev({ type: "thermostat", state: "5" }), -0.5)).toBe(5);
    expect(nextSetpoint(dev({ type: "thermostat", state: null }), 0.5)).toBeNull();
  });

  it("erklärt den Steuerungsmodus", () => {
    expect(controlNote("readonly")).toContain("nur lesen");
    expect(controlNote("test")).toContain("Testgerät");
    expect(controlNote("full")).toBeNull();
  });
});

function panel(devices: DeviceInfo[], over: Partial<Parameters<typeof DevicePanel>[0]> = {}) {
  const onCommand = vi.fn();
  render(<DevicePanel devices={devices} control="full" error={null} room="" onCommand={onCommand} {...over} />);
  return onCommand;
}

describe("DevicePanel", () => {
  it("schaltet ein Licht per Schalter", () => {
    const onCommand = panel([dev({})]);
    fireEvent.click(screen.getByRole("switch", { name: "Wohnzimmer Licht einschalten" }));
    expect(onCommand).toHaveBeenCalledWith("licht", "on");
  });

  it("schaltet ein eingeschaltetes Licht aus", () => {
    const onCommand = panel([dev({ state: "ON" })]);
    fireEvent.click(screen.getByRole("switch", { name: "Wohnzimmer Licht ausschalten" }));
    expect(onCommand).toHaveBeenCalledWith("licht", "off");
  });

  it("zeigt keine Bedienelemente für nicht steuerbare oder offline Geräte", () => {
    panel([dev({ controllable: false }), dev({ id: "x", name: "Offline", online: false })]);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("bedient Rollläden und Thermostate", () => {
    const onCommand = panel([
      dev({ id: "rollo", name: "Rollo", type: "shutter", state: "50" }),
      dev({ id: "heiz", name: "Heizung", type: "thermostat", state: "21", unit: "°C" }),
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Rollo runter" }));
    fireEvent.click(screen.getByRole("button", { name: "Heizung wärmer" }));
    expect(onCommand).toHaveBeenNthCalledWith(1, "rollo", "down");
    expect(onCommand).toHaveBeenNthCalledWith(2, "heiz", "21.5");
  });

  it("kennzeichnet Geräte mit Bestätigungspflicht", () => {
    const onCommand = panel([dev({ id: "tuer", name: "Haustür", type: "lock", risk: "high", state: "locked" })]);
    expect(screen.getByText("Bestätigung nötig")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Entriegeln" }));
    expect(onCommand).toHaveBeenCalledWith("tuer", "unlock");
  });

  it("filtert nach Raum und erklärt leere Zustände", () => {
    panel([dev({}), dev({ id: "k", name: "Küchenlicht", room: "Küche" })], { room: "Küche" });
    expect(screen.getByText("Küchenlicht")).toBeInTheDocument();
    expect(screen.queryByText("Wohnzimmer Licht")).not.toBeInTheDocument();
  });

  it("weist auf eine leere Allowlist hin, zeigt Fehler und Modus", () => {
    panel([], { control: "readonly", error: "devices.yaml: doppelte id 'x'." });
    expect(screen.getByText(/keine Geräte freigegeben/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("doppelte id");
    expect(screen.getByText(/nur lesen/)).toBeInTheDocument();
  });
});

const confirm: PendingConfirm = {
  id: "c1",
  device: "tuer",
  command: "unlock",
  summary: "Soll ich 'Haustür' entriegeln?",
  expiresIn: 60,
  receivedAt: Date.now(),
};

describe("ConfirmDialog", () => {
  it("fragt nach und startet mit Fokus auf Abbrechen", () => {
    const onAnswer = vi.fn();
    render(<ConfirmDialog confirm={confirm} onAnswer={onAnswer} />);
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Haustür");
    expect(screen.getByRole("button", { name: "Abbrechen" })).toHaveFocus();
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("bestätigt nur mit ausdrücklichem Klick", () => {
    const onAnswer = vi.fn();
    render(<ConfirmDialog confirm={confirm} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Ja, ausführen" }));
    expect(onAnswer).toHaveBeenCalledWith(true);
  });

  it("lehnt mit Abbrechen und Escape ab", () => {
    const onAnswer = vi.fn();
    render(<ConfirmDialog confirm={confirm} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onAnswer).toHaveBeenNthCalledWith(1, false);
    expect(onAnswer).toHaveBeenNthCalledWith(2, false);
  });

  it("lehnt nach Ablauf selbst ab", () => {
    vi.useFakeTimers();
    const onAnswer = vi.fn();
    render(<ConfirmDialog confirm={{ ...confirm, expiresIn: 2, receivedAt: Date.now() }} onAnswer={onAnswer} />);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(onAnswer).toHaveBeenCalledWith(false);
    vi.useRealTimers();
  });
});

describe("store: Geräte und Rückfragen", () => {
  it("übernimmt Liste, Änderungen und Modus", () => {
    let s = reducer(initialState, {
      kind: "server",
      event: { type: "device.list", control: "test", error: null, devices: [dev({})] },
    });
    expect(s.control).toBe("test");
    s = reducer(s, {
      kind: "server",
      event: { type: "device.state", id: "licht", state: "ON", unit: null, online: true },
    });
    expect(s.devices[0]?.state).toBe("ON");
  });

  it("zeigt Rückfragen an und schließt sie bei confirm.resolved der gleichen ID", () => {
    let s = reducer(initialState, {
      kind: "server",
      event: { type: "confirm.request", id: "c1", device: "tuer", command: "unlock", summary: "Soll ich?", expires_in: 60 },
    });
    expect(s.confirm?.id).toBe("c1");
    s = reducer(s, { kind: "server", event: { type: "confirm.resolved", id: "andere" } });
    expect(s.confirm?.id).toBe("c1");
    s = reducer(s, { kind: "server", event: { type: "confirm.resolved", id: "c1" } });
    expect(s.confirm).toBeNull();
  });

  it("öffnet das Geräte-Panel lokal auf der Stage", () => {
    const s = reducer(initialState, { kind: "showDevices" });
    expect(s.stage[0]?.kind).toBe("devices");
    expect(s.stageIndex).toBe(0);
  });
});
