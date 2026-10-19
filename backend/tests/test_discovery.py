import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from cat.agent.tools import ToolContext
from cat.audit import AuditLog
from cat.config import Settings
from cat.devices.allowlist import parse_allowlist
from cat.devices.commands import DeviceError
from cat.devices.confirm import ConfirmManager
from cat.devices.discovery import DiscoverConfig, discover_openhab
from cat.devices.models import DeviceSpec
from cat.devices.service import DeviceService, RawState
from cat.devices.tools import build_device_tools
from cat.plugins.base import PluginContext
from cat.plugins.openhab import OpenHabPlugin
from cat.stage.store import StageStore
from cat.ws.protocol import DeviceStateEvent, ServerEvent


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


ITEMS = [
    item("room_child1", "Group", "Romans Zimmer", ["Firstfloor"], ["Location"]),
    item("Firstfloor", "Group", "Obergeschoss", [], ["Location"]),
    item("Rollo_Roman", "Group", "Rollo Roman", ["room_child1"], ["Equipment"]),
    item("Rollo_Roman_Control", "Rollershutter", None, ["Rollo_Roman"], ["Point"], "0"),
    item(
        "Rollo_Roman_Romans_Zimmer__Control",
        "Rollershutter",
        "Romans Rollo",
        ["room_child1"],
        ["Blinds", "Point"],
    ),
    item(
        "Romans_Shelly_Betrieb",
        "Switch",
        "Deckenlicht Roman",
        ["room_child1"],
        ["Power", "Switch"],
        "OFF",
    ),
    item("Lampe_Hell", "Dimmer", "Helligkeit", ["room_child1"], ["Light", "Control"], "40"),
    item("Hue_A_Farbe", "Color", "Farbe", ["room_child1"], ["Light"], "30,40,50"),
    item("Hue_B_Farbe", "Color", "Farbe", ["room_child1"], ["Light"], "30,40,60"),
    item("Hue_A_Colortemperature", "Dimmer", "Farbtemperatur", ["room_child1"], [], "61"),
    item("TL_Wand_Color_Sc1", "Color", "Wandlampe Farbe Scenario1", ["room_child1"], ["Point"]),
    item(
        "Temp_Roman",
        "Number:Temperature",
        "Temperatur Roman",
        ["room_child1"],
        ["Measurement", "Temperature"],
        "21.5 °C",
    ),
    item("Text_Technik", "String", "Technischer Text", ["room_child1"], [], "abc"),
    item("StatBeschattung", "Switch", "Status Beschattung", ["room_child1"], ["Point"], "OFF"),
    item("Warmepumpe_Pumpe", "Switch", "Umwälzpumpe", ["room_child1", "WP"], ["Point"], "ON"),
    item("WP", "Group", "Wärmepumpe", ["room_child1"], ["Equipment"]),
    item("Tor_Schloss", "Switch", "Haustür Schloss", ["room_child1"], [], "ON"),
    item("Trig_Reboot", "Switch", "Reboot Trigger", [], [], "NULL"),
    item("Ohne_Raum", "Switch", "Steckdose Keller-Regal", [], [], "ON"),
    item("Bild", "Image", None, [], [], "NULL"),
]
CFG = DiscoverConfig(enabled=True)


def found(
    items: list[dict[str, Any]] | None = None,
    cfg: DiscoverConfig = CFG,
    taken: set[str] | None = None,
):
    out = discover_openhab(items if items is not None else ITEMS, cfg, taken)
    return {d.spec.item: d for d in out}


def test_room_comes_from_the_semantic_model_through_equipment_groups() -> None:
    devices = found()
    assert devices["Rollo_Roman_Control"].spec.room == "Romans Zimmer"  # über Equipment-Gruppe
    assert devices["Rollo_Roman_Romans_Zimmer__Control"].spec.room == "Romans Zimmer"
    assert devices["Ohne_Raum"].spec.room == "Haus"  # kein Location über dem Item


def test_types_follow_the_openhab_item_types() -> None:
    d = found()
    assert d["Rollo_Roman_Romans_Zimmer__Control"].spec.type == "shutter"
    assert d["Romans_Shelly_Betrieb"].spec.type == "switch"
    assert d["Lampe_Hell"].spec.type == "dimmer"
    assert d["Hue_A_Farbe"].spec.type == "dimmer"
    assert d["Temp_Roman"].spec.type == "sensor"
    assert d["Text_Technik"].spec.type == "sensor"
    assert "Rollo_Roman" not in d and "Bild" not in d and "room_child1" not in d  # Gruppen, Bilder


def test_light_tag_makes_a_light() -> None:
    items = [item("L", "Switch", "Flurlicht", [], ["Light", "Switch"], "ON")]
    assert found(items)["L"].spec.type == "light"


def test_the_label_becomes_the_name_and_you_can_ask_for_the_item_name_too() -> None:
    spec = found()["Rollo_Roman_Romans_Zimmer__Control"].spec
    assert spec.name == "Romans Rollo"
    assert "Rollo Roman Romans Zimmer Control" in spec.synonyms
    plain = found()["Rollo_Roman_Control"].spec  # Etikett = Item-Name: lesbar machen
    assert plain.name == "Rollo Roman Control"


def test_duplicate_labels_in_one_room_use_the_readable_item_names() -> None:
    d = found()
    assert d["Hue_A_Farbe"].spec.name == "Hue A Farbe"
    assert d["Hue_B_Farbe"].spec.name == "Hue B Farbe"


def test_names_and_ids_are_unique_and_valid() -> None:
    items = [
        item("A_X", "Switch", "Licht", ["r"], [], "ON"),
        item("A.X", "Switch", "Licht", ["r"], [], "ON"),
        item("r", "Group", "Raum", [], ["Location"]),
    ]
    specs = [d.spec for d in discover_openhab(items, CFG)]
    assert len({s.id for s in specs}) == 2
    assert len({(s.room, s.name) for s in specs}) == 2
    for s in specs:
        DeviceSpec.model_validate(s.model_dump())  # id-Regel und Längen


def test_technical_and_dangerous_things_are_read_only() -> None:
    d = found()
    for name in ("StatBeschattung", "Warmepumpe_Pumpe", "Tor_Schloss", "Trig_Reboot"):
        assert d[name].spec.type == "sensor", name  # Cat darf sie lesen, aber nie schalten


def test_listing_hides_scenarios_color_temperatures_and_plain_text() -> None:
    d = found()
    assert d["Romans_Shelly_Betrieb"].spec.listed and d["Temp_Roman"].spec.listed
    assert d["Rollo_Roman_Romans_Zimmer__Control"].spec.listed
    for name in ("TL_Wand_Color_Sc1", "Hue_A_Colortemperature", "Text_Technik", "Trig_Reboot"):
        assert not d[name].spec.listed, name


def test_states_come_along_for_a_bulk_seed() -> None:
    d = found()
    assert d["Temp_Roman"].state == "21.5 °C" and d["Lampe_Hell"].state == "40"


def test_manual_entries_win_and_exclude_patterns_hide() -> None:
    assert "Lampe_Hell" not in found(taken={"Lampe_Hell"})
    assert "Lampe_Hell" not in found(
        cfg=DiscoverConfig(enabled=True, exclude_patterns=["helligkeit"])
    )


def test_custom_patterns_extend_the_defaults_and_broken_ones_are_ignored() -> None:
    cfg = DiscoverConfig(enabled=True, readonly_patterns=["deckenlicht", "(kaputt"])
    assert found(cfg=cfg)["Romans_Shelly_Betrieb"].spec.type == "sensor"
    assert found(cfg=cfg)["Lampe_Hell"].spec.type == "dimmer"


def test_group_cycles_do_not_hang() -> None:
    items = [
        item("A", "Group", "A", ["B"]),
        item("B", "Group", "B", ["A"]),
        item("S", "Switch", "Schalter", ["A"], [], "ON"),
    ]
    assert found(items)["S"].spec.room == "Haus"


def test_real_world_size_is_fast_and_mostly_unlisted() -> None:
    items = [item("Raum", "Group", "Raum", [], ["Location"])]
    items += [item(f"Sensor_{i}", "Number", f"Wert {i}", ["Raum"], [], str(i)) for i in range(400)]
    items += [
        item(f"Licht_{i}", "Switch", f"Licht {i}", ["Raum"], ["Light"], "OFF") for i in range(30)
    ]
    out = discover_openhab(items, CFG)
    assert len(out) == 430
    assert sum(d.spec.listed for d in out) == 30  # nur die Schalter, Rohwerte nur auf Nachfrage


# --- Allowlist und Dienst ---


def test_allowlist_parses_the_discover_section() -> None:
    yaml_text = (
        "discover:\n  openhab:\n    enabled: true\n    exclude_patterns: [foo]\ndevices: []\n"
    )
    allow = parse_allowlist(yaml_text)
    assert allow.error is None and allow.discover["openhab"].enabled
    assert parse_allowlist("discover:\n  homeassistant: {enabled: true}\ndevices: []\n").error
    assert parse_allowlist("discover:\n  openhab: {unbekannt: 1}\ndevices: []\n").error


class Harness:
    def __init__(
        self, tmp_path: Path, yaml_text: str = "devices: []\n", control: str = "full"
    ) -> None:
        self.events: list[ServerEvent] = []

        async def emit(event: ServerEvent) -> None:
            self.events.append(event)

        self.service = DeviceService(
            parse_allowlist(yaml_text),
            control,  # type: ignore[arg-type]
            emit,
            AuditLog(tmp_path / "a.jsonl"),
            ConfirmManager(emit, lambda: True, timeout_s=0.2),
        )
        self.service.settle_delay = 0

    def load(self, items: list[dict[str, Any]] = ITEMS) -> None:
        self.service.set_discovered([d.spec for d in discover_openhab(items, CFG)])


def test_service_lists_only_listed_but_finds_everything(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.load()
    listed = {i.name for i in h.service.snapshot()}
    assert "Romans Rollo" in listed and "Technischer Text" not in listed
    assert {i.name for i in h.service.snapshot(include_unlisted=True)} >= {"Technischer Text"}
    assert [i.name for i in h.service.search("technischer text")][:1] == ["Technischer Text"]
    assert any(i.name == "Romans Rollo" for i in h.service.search("Rollo Roman"))
    assert h.service.search("") == []


def test_manual_entries_override_discovered_ones(tmp_path: Path) -> None:
    yaml_text = (
        "devices:\n  - {id: mein_licht, backend: openhab, item: Lampe_Hell, name: Leselampe, "
        "room: Büro, type: light}\n"
    )
    h = Harness(tmp_path, yaml_text)
    h.load()
    spec = h.service.resolve("Leselampe")
    assert (spec.room, spec.type) == ("Büro", "light")
    assert sum(s.item == "Lampe_Hell" for s in h.service.specs) == 1


def test_resolve_is_forgiving_but_never_guesses(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.load()
    assert h.service.resolve("romans rollo").item == "Rollo_Roman_Romans_Zimmer__Control"
    assert h.service.resolve("ROMANS ROLLO").name == "Romans Rollo"
    assert (
        h.service.resolve("Rollo_Roman_Romans_Zimmer__Control").name == "Romans Rollo"
    )  # Item-Name
    assert h.service.resolve("Deckenlicht Roman").type == "switch"
    with pytest.raises(DeviceError, match="Ähnliche Geräte"):
        h.service.resolve("Rollo Roma")  # kein Treffer ist sicher, aber Vorschläge kommen
    with pytest.raises(DeviceError, match="gibt es nicht"):
        h.service.resolve("Raumschiff")


async def test_state_events_only_for_listed_devices(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.load()
    await h.service.on_state_change("openhab", "Temp_Roman", RawState("22", "°C"))
    await h.service.on_state_change("openhab", "Text_Technik", RawState("xyz"))
    ids = [e.id for e in h.events if isinstance(e, DeviceStateEvent)]
    assert ids == ["temp_roman"]  # technische Geräte füllen den Browser nicht
    info = next(i for i in h.service.snapshot(include_unlisted=True) if i.id == "text_technik")
    assert info.state == "xyz"  # gemerkt wird alles


async def test_refresh_all_skips_devices_with_a_known_state(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.load()
    reads: list[str] = []

    class Backend:
        async def read(self, spec: DeviceSpec) -> RawState:
            reads.append(spec.item)
            return RawState("1")

        async def send(self, spec: DeviceSpec, command: str) -> None: ...

    h.service.register_backend("openhab", Backend())
    h.service.seed_states("openhab", {"Temp_Roman": RawState("21", "°C")})
    await h.service.refresh_all("openhab", skip_known=True)
    assert "Temp_Roman" not in reads and "Lampe_Hell" in reads


async def test_discovered_devices_are_controllable_in_full_mode_but_read_only_ones_are_not(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path, control="full")
    h.load()
    sent: list[tuple[str, str]] = []

    class Backend:
        async def read(self, spec: DeviceSpec) -> RawState:
            return RawState("OFF")

        async def send(self, spec: DeviceSpec, command: str) -> None:
            sent.append((spec.item, command))

    h.service.register_backend("openhab", Backend())
    assert "Befehl gesendet" in await h.service.command("Romans Rollo", "down")
    assert sent == [("Rollo_Roman_Romans_Zimmer__Control", "down")]
    with pytest.raises(DeviceError):
        await h.service.command("Haustür Schloss", "on")  # nur lesbar: kein Befehl für Sensoren
    assert len(sent) == 1


async def test_tools_search_limit_and_summary(tmp_path: Path) -> None:
    items = [item("Raum", "Group", "Küche", [], ["Location"])]
    items += [
        item(f"Licht_{i:02d}", "Switch", f"Lampe {i:02d}", ["Raum"], ["Light"], "OFF")
        for i in range(50)
    ]
    items += [item("Roh", "String", "Rohtext", ["Raum"], [], "x")]
    h = Harness(tmp_path)
    h.load(items)
    emit_ctx = ToolContext(emit=lambda _: asyncio.sleep(0), stage=StageStore())  # type: ignore[arg-type]
    list_devices = {t.name: t for t in build_device_tools(h.service)}["list_devices"].handler
    overview = await list_devices({}, emit_ctx)
    assert overview.count("\n") < 50 and "weitere" in overview
    assert "Räume: Küche (50)" in overview and "1 technische Geräte" in overview
    found_text = await list_devices({"query": "Rohtext"}, emit_ctx)
    assert "Rohtext" in found_text
    assert "kein Gerät" in await list_devices({"query": "Raumschiff"}, emit_ctx)
    assert "Lampe 07" in await list_devices({"query": "Lampe 07"}, emit_ctx)


# --- Plugin: nur lesen und Befehle, nie ändern ---


class Recorder:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.requests: list[httpx.Request] = []
        self.items = items

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path == "/rest/items":
            return httpx.Response(200, json=self.items)
        if request.method == "GET" and request.url.path.startswith("/rest/items/"):
            return httpx.Response(200, json={"state": "OFF"})
        if request.method == "POST":
            return httpx.Response(200)
        return httpx.Response(405)


async def test_plugin_discovers_with_one_get_and_changes_nothing_in_openhab(tmp_path: Path) -> None:
    recorder = Recorder(ITEMS)
    h = Harness(tmp_path, "discover:\n  openhab: {enabled: true}\ndevices: []\n")
    client = httpx.AsyncClient(base_url="http://oh", transport=httpx.MockTransport(recorder))
    plugin = OpenHabPlugin(h.service, client=client)
    count = await plugin.discover()
    assert count > 10
    assert len(recorder.requests) == 1  # eine Sammelabfrage statt Hunderten Einzelabfragen
    request = recorder.requests[0]
    assert request.method == "GET" and "fields" in request.url.params
    assert {i.state for i in h.service.snapshot(include_unlisted=True) if i.id == "temp_roman"} == {
        "21.5"
    }

    await h.service.command("Romans Rollo", "down")
    await h.service.command("Deckenlicht Roman", "on")
    methods = {(r.method, r.url.path.startswith("/rest/items")) for r in recorder.requests}
    assert methods <= {("GET", True), ("POST", True)}  # nie PUT, DELETE oder PATCH
    posts = [r for r in recorder.requests if r.method == "POST"]
    assert all(r.headers["content-type"] == "text/plain" for r in posts)
    assert {r.url.path for r in posts} == {
        "/rest/items/Rollo_Roman_Romans_Zimmer__Control",
        "/rest/items/Rollo_Roman_Control",  # Zwilling mit Wert: bekommt den Befehl ebenfalls
        "/rest/items/Romans_Shelly_Betrieb",
    }
    await client.aclose()


async def test_plugin_without_discover_section_stays_quiet(tmp_path: Path) -> None:
    recorder = Recorder(ITEMS)
    h = Harness(tmp_path)
    client = httpx.AsyncClient(base_url="http://oh", transport=httpx.MockTransport(recorder))
    assert await OpenHabPlugin(h.service, client=client).discover() == 0
    assert recorder.requests == []
    await client.aclose()


async def test_plugin_reports_openhab_errors_without_crashing(tmp_path: Path) -> None:
    h = Harness(tmp_path, "discover:\n  openhab: {enabled: true}\ndevices: []\n")
    for response in (httpx.Response(503), httpx.Response(401), httpx.Response(200, json={"x": 1})):
        client = httpx.AsyncClient(
            base_url="http://oh", transport=httpx.MockTransport(lambda _, r=response: r)
        )
        with pytest.raises(DeviceError):
            await OpenHabPlugin(h.service, client=client).discover()
        await client.aclose()


async def test_plugin_start_discovers_and_reads_the_rest(tmp_path: Path) -> None:
    recorder = Recorder(ITEMS)
    h = Harness(tmp_path, "discover:\n  openhab: {enabled: true}\ndevices: []\n")
    client = httpx.AsyncClient(base_url="http://oh", transport=httpx.MockTransport(recorder))
    plugin = OpenHabPlugin(h.service, client=client, backoff_s=lambda _: 0.05)

    async def publish(_: object) -> None: ...

    await plugin.start(PluginContext(Settings(_env_file=None, static_dir=None), publish))  # type: ignore[call-arg]
    await asyncio.sleep(0.3)
    await plugin.stop()
    assert any(s.item == "Romans_Shelly_Betrieb" for s in h.service.specs)
    singles = [r for r in recorder.requests if r.url.path.startswith("/rest/items/")]
    assert singles == []  # alle Zustände kamen aus der Sammelabfrage
    assert json.dumps(sorted({r.method for r in recorder.requests}))


async def test_unknown_state_points_to_similar_devices_with_a_value(tmp_path: Path) -> None:
    items = [
        item("R", "Group", "Romans Zimmer", [], ["Location"]),
        item("A", "Rollershutter", "Romans Rollo", ["R"], [], "NULL"),
        item("B", "Rollershutter", "Rollo Roman Control", ["R"], [], "0"),
        item("C", "Rollershutter", "Garagentor Markise", ["R"], [], "50"),
        item("D", "Rollershutter", "Küchenrollo", ["Other"], [], "10"),
    ]
    h = Harness(tmp_path)
    h.load(items)
    h.service.seed_states("openhab", {"B": RawState("0"), "C": RawState("50"), "D": RawState("10")})
    tool = {t.name: t for t in build_device_tools(h.service)}["get_state"]

    class Backend:
        async def read(self, spec: DeviceSpec) -> RawState:
            return RawState(None) if spec.item == "A" else RawState("0")

        async def send(self, spec: DeviceSpec, command: str) -> None: ...

    h.service.register_backend("openhab", Backend())
    ctx = ToolContext(emit=lambda _: asyncio.sleep(0), stage=StageStore())  # type: ignore[arg-type]
    out = await tool.handler({"device": "Romans Rollo"}, ctx)
    assert "unbekannt (kein Wert gemeldet)" in out and "Rollo Roman Control" in out
    assert "Garagentor" not in out and "Küchenrollo" not in out  # nur Ähnliches im selben Raum
    known = await tool.handler({"device": "Rollo Roman Control"}, ctx)
    assert "Hinweis" not in known


def test_twin_items_share_state_and_only_the_nice_name_is_listed() -> None:
    d = found()
    nice = d["Rollo_Roman_Romans_Zimmer__Control"]
    assert nice.spec.twins == ["Rollo_Roman_Control"] and nice.state == "0"  # Wert vom Zwilling
    assert d["Rollo_Roman_Control"].spec.listed is False and nice.spec.listed


def test_lamps_with_similar_names_are_not_mistaken_for_twins() -> None:
    items = [
        item("Hue_Lampe_Terrasse_Helligkeit", "Dimmer", "Terrasse", [], ["Point"], "50"),
        item("Hue_Lampe_Wohnzimmer_Helligkeit", "Dimmer", "Wohnzimmer", [], ["Point"], "NULL"),
    ]
    out = {d.spec.item: d for d in discover_openhab(items, DiscoverConfig(enabled=True))}
    assert out["Hue_Lampe_Wohnzimmer_Helligkeit"].spec.twins == []
    assert out["Hue_Lampe_Terrasse_Helligkeit"].spec.listed
