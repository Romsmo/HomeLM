"""Befehle an Geräte, die es in openHAB gibt: "Schließe die Markisen" (20.11./21.11.2026).

Die Items stammen aus dem echten openHAB (Markisen: je ein Rollladen mit schönem Etikett ohne
Wert, ein Technik-Rollladen mit Wert und ein Sensor "... Position Manuell").
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from cat.agent.tools import ToolContext, ToolError
from cat.audit import AuditLog
from cat.devices.allowlist import parse_allowlist
from cat.devices.commands import DeviceError
from cat.devices.confirm import ConfirmManager
from cat.devices.discovery import DiscoverConfig, discover_openhab
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.devices.tools import build_device_tools
from cat.stage.store import StageStore
from cat.ws.protocol import ServerEvent


def item(name: str, type_: str, label: str | None = None, groups: list[str] | None = None,
         tags: list[str] | None = None, state: str | None = "NULL") -> dict[str, Any]:  # fmt: skip
    return {
        "name": name,
        "type": type_,
        "label": label if label is not None else name,
        "groupNames": groups or [],
        "tags": tags or [],
        "state": state,
    }


def awning_items() -> list[dict[str, Any]]:
    items = [
        item("outside", "Group", "Draußen", [], ["Location"]),
        item(
            "Terrassenmarkisen", "Group", "Terrassenmarkisen", ["outside"], ["Terrace", "Location"]
        ),
        item("gMarkisenTahoma", "Group", "Markisen Tahoma", ["Terrassenmarkisen"], ["Location"]),
    ]
    for side in ("Nord", "Ost", "West"):
        items += [
            item(f"Markise_{side}", "Group", f"Markise {side}", ["gMarkisenTahoma"], ["Equipment"]),
            item(
                f"Markise_{side}_Control",
                "Rollershutter",
                None,
                [f"Markise_{side}"],
                ["Point"],
                "0",
            ),
            item(
                f"Markise_{side}_Terrasse_Control",
                "Rollershutter",
                f"Markise {side}",
                ["Terrassenmarkisen"],
                ["Point"],
            ),
            item(
                f"Markise{side}PosManual",
                "Number",
                f"Markise {side} Position Manuell",
                ["Terrassenmarkisen"],
                ["Point"],
            ),
        ]
    items += [
        item("room_roman", "Group", "Romans Zimmer", [], ["Location"]),
        item("Rollo_Roman_Control", "Rollershutter", "Romans Rollo", ["room_roman"], [], "0"),
        item("room_marius", "Group", "Marius Zimmer", [], ["Location"]),
        item("Rollo_Marius_Control", "Rollershutter", "Marius Rollo", ["room_marius"], [], "0"),
    ]
    return items


class FakeBackend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec: DeviceSpec) -> RawState:
        return RawState("0")

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.item, command))


class Setup:
    def __init__(self, tmp_path: Path, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.events: list[ServerEvent] = []
        self.backend = FakeBackend()
        self.reads = 0

        async def emit(event: ServerEvent) -> None:
            self.events.append(event)

        self.service = DeviceService(
            parse_allowlist("devices: []\n"),
            "full",
            emit,
            AuditLog(tmp_path / "a.jsonl"),
            ConfirmManager(emit, lambda: True, timeout_s=0.2),
        )
        self.service.settle_delay = 0
        self.service.register_backend("openhab", self.backend)
        self.service.rediscover = self.discover
        self.load()
        tools = {t.name: t for t in build_device_tools(self.service)}
        self.set_state = tools["set_state"].handler
        self.get_state = tools["get_state"].handler

    def load(self) -> None:
        self.service.set_discovered(
            [d.spec for d in discover_openhab(self.items, DiscoverConfig(enabled=True))]
        )

    async def discover(self) -> int:
        self.reads += 1
        self.load()
        return len(self.service.specs)

    def ctx(self, text: str) -> ToolContext:
        ctx = ToolContext(emit=lambda _: asyncio.sleep(0), stage=StageStore())  # type: ignore[arg-type]
        ctx.user_text = text
        return ctx


def test_the_sensor_does_not_win_over_the_shutter(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    # Ohne Vorrang für Steuerbares wäre das ein Sensor ("... Position Manuell").
    spec = s.service.resolve("Markise Nord", only_controllable=True)
    assert spec.type == "shutter" and spec.item == "Markise_Nord_Terrasse_Control"


async def test_close_the_awnings_moves_all_three(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    ctx = s.ctx("Schließe die Markisen")
    out = await s.set_state({"device": "Markisen", "command": "off"}, ctx)  # "off" vom Modell
    sent = {(i, c) for i, c in s.backend.sent}
    for side in ("Nord", "Ost", "West"):
        assert (f"Markise_{side}_Terrasse_Control", "down") in sent  # schöner Name
        # Der Technik-Zwilling mit Wert bekommt den Befehl im Plugin dazu (docs/devices.md).
        twin = s.service.resolve(f"Markise_{side}_Terrasse_Control").twins
        assert twin == [f"Markise_{side}_Control"]
    assert all(c == "down" for _, c in s.backend.sent)
    assert "Position" not in out and "Sensor" not in out
    assert not any("Rollo" in i for i, _ in s.backend.sent)  # Rollos bleiben in Ruhe


@pytest.mark.parametrize("word", ["Markisen", "die Markisen", "alle Markisen", "Terrassenmarkisen"])
async def test_group_words_for_awnings(tmp_path: Path, word: str) -> None:
    s = Setup(tmp_path, awning_items())
    await s.set_state({"device": word, "command": "up"}, s.ctx("Öffne " + word))
    assert len({i for i, _ in s.backend.sent if i.endswith("_Terrasse_Control")}) == 3


async def test_a_single_awning_by_name(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    await s.set_state({"device": "Markise Nord", "command": "down"}, s.ctx("Markise Nord zu"))
    assert {i for i, _ in s.backend.sent} == {"Markise_Nord_Terrasse_Control"}


async def test_plain_rollos_across_rooms_stay_a_question(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    with pytest.raises(ToolError):
        await s.set_state({"device": "Rollos", "command": "down"}, s.ctx("Schließe die Rollos"))
    assert s.backend.sent == []  # nie raten, welches Zimmer


async def test_a_new_item_is_found_without_waiting_for_the_ten_minute_scan(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    # Nach dem Start kommt ein Item dazu; die regelmäßige Erkennung hat es noch nicht gesehen.
    s.items.append(item("room_gast", "Group", "Gästezimmer", [], ["Location"]))
    s.items.append(item("Gaestelampe", "Switch", "Gästelampe", ["room_gast"], ["Light"], "OFF"))
    assert not any(sp.item == "Gaestelampe" for sp in s.service.specs)
    await s.set_state({"device": "Gästelampe", "command": "on"}, s.ctx("Gästelampe an"))
    assert ("Gaestelampe", "on") in s.backend.sent and s.reads == 1


async def test_get_state_also_looks_again_for_unknown_names(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    s.items.append(item("Gaestelampe", "Switch", "Gästelampe", [], ["Light"], "ON"))
    out = await s.get_state({"device": "Gästelampe"}, s.ctx("Ist die Gästelampe an?"))
    assert "Gästelampe" in out and s.reads == 1


async def test_unknown_names_refresh_at_most_every_few_seconds(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    for _ in range(3):
        with pytest.raises(ToolError):
            await s.set_state({"device": "Raumschiff", "command": "on"}, s.ctx("Raumschiff an"))
    assert s.reads == 1  # nicht bei jeder Anfrage openHAB abfragen


async def test_only_a_sensor_exists_says_so_after_one_fresh_look(tmp_path: Path) -> None:
    items = [item("Temp", "Number:Temperature", "Wetterfühler", [], [], "20 °C")]
    s = Setup(tmp_path, items)
    with pytest.raises((ToolError, DeviceError), match="Sensor"):
        await s.set_state({"device": "Wetterfühler", "command": "on"}, s.ctx("Wetterfühler an"))
    assert s.reads == 1 and s.backend.sent == []


async def test_off_without_clear_wish_is_not_turned_into_a_direction(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    with pytest.raises(ToolError):
        await s.set_state(
            {"device": "Markise Nord", "command": "off"}, s.ctx("Mach Markise Nord aus")
        )
    assert s.backend.sent == []
