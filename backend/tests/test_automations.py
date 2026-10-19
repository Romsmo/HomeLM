import httpx

from cat.agent.tools import ToolContext
from cat.plugins.openhab.automations import describe, filter_by_query, normalize_state, parse_rules
from cat.stage.store import StageStore
from tests.test_speed import YAML, make

RULES = [
    {
        "name": "Treppenhaus Beschattung Ein Ia",
        "status": {"status": "IDLE", "statusDetail": "NONE"},
    },
    {
        "name": "Treppenhaus Beschattung Ein Ib",
        "status": {"status": "IDLE", "statusDetail": "NONE"},
    },
    {
        "name": "Treppenhaus Beschattung Ein II",
        "status": {"status": "IDLE", "statusDetail": "NONE"},
    },
    {
        "name": "Zeitschaltung ein",
        "status": {"status": "UNINITIALIZED", "statusDetail": "DISABLED"},
    },
    {"name": "Reboot PI", "status": {"status": "IDLE", "statusDetail": "NONE"}},
    {"name": "Reboot PI", "status": {"status": "IDLE", "statusDetail": "NONE"}},
    {"name": "Treppenhaus Beschattung 100%", "status": {"status": "RUNNING"}},
]


def test_rules_are_grouped_by_base_name_and_disabled_ones_are_known() -> None:
    items = {a.name: a for a in parse_rules(RULES)}
    assert items["Treppenhaus Beschattung Ein"].count == 3
    assert items["Reboot PI"].count == 2
    assert items["Zeitschaltung ein"].active is False
    assert items["Treppenhaus Beschattung 100%"].active  # läuft gerade


def test_descriptions_answer_active_disabled_and_overview() -> None:
    items = parse_rules(RULES)
    assert describe(items, "aktiv").startswith("Aktiv sind 6 Automationen: ")
    assert describe(items, "aus") == "Deaktiviert sind 1 Automationen: Zeitschaltung ein."
    assert "7 Automationen (6 aktiv, 1 deaktiviert)" in describe(items, None)
    assert describe([], None, "x") == "Dazu gibt es keine Automation."


def test_query_narrows_and_generic_words_do_not() -> None:
    items = parse_rules(RULES)
    assert [a.name for a in filter_by_query(items, "Automationen")] == [a.name for a in items]
    assert [a.name for a in filter_by_query(items, "Beschattungen Treppenhaus")] == [
        "Treppenhaus Beschattung 100%",
        "Treppenhaus Beschattung Ein",
    ]
    assert normalize_state("an") == "aktiv" and normalize_state("deaktiviert") == "aus"
    assert normalize_state("weiß nicht") is None


async def test_tool_reads_rules_with_get_only_and_answers_directly(tmp_path) -> None:
    from cat.plugins.openhab import OpenHabPlugin

    service, _ = make(tmp_path)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RULES)

    client = httpx.AsyncClient(base_url="http://oh", transport=httpx.MockTransport(handler))
    plugin = OpenHabPlugin(service, client=client)
    tool = plugin.tools()[0]

    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    text = await tool.handler({"state": "an"}, ctx)
    assert text.startswith("Aktiv sind") and ctx.final_replies == [text]
    assert [r.method for r in seen] == ["GET"] and seen[0].url.path == "/rest/rules"
    await client.aclose()
    assert YAML  # Fixture wird importiert, damit make() dieselbe Allowlist nutzt


def test_state_words_in_the_query_do_not_filter_the_names() -> None:
    items = parse_rules(RULES)
    assert filter_by_query(items, "aktiv") == items  # das Modell schreibt manchmal A|aktiv
    assert filter_by_query(items, "alle aktiven") == items
    assert [a.name for a in filter_by_query(items, "Treppenhaus aktiv")] == [
        "Treppenhaus Beschattung 100%",
        "Treppenhaus Beschattung Ein",
    ]
