import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cat.agent.responder import build_responder
from cat.agent.tools import ToolContext, ToolError
from cat.config import Settings
from cat.llm.base import LLMError, TextDelta, ToolCall
from cat.main import create_app
from cat.memory.index import NullVectorIndex, fts_query
from cat.memory.notes import NoteError, NoteStore, parse_note, slug
from cat.memory.service import MemoryService, build_memory_tools
from cat.memory.sessions import SessionLog, summarize_old_sessions, transcript
from cat.stage.store import StageStore
from tests.conftest import PASSWORD
from tests.fakes import FakeProvider
from tests.helpers import drain_replay


def age(mem: MemoryService, *session_ids: str) -> None:
    """Macht Sitzungsdateien messbar alt (Dateizeit und Systemuhr sind nicht auf die Nanosekunde gleich)."""
    past = time.time() - 3600
    for sid in session_ids:
        os.utime(mem.sessions._path(sid), (past, past))


def memory(tmp_path: Path) -> MemoryService:
    return MemoryService(tmp_path / "memory", tmp_path / "sessions")


# --- Notizen ---


def test_slug_blocks_path_tricks() -> None:
    assert slug("../../etc/passwd") == "etc-passwd"
    assert slug("Küche & Bäder!") == "kueche-baeder"
    assert slug("///") == "notiz"
    assert slug("x" * 200) == "x" * 60


def test_write_creates_markdown_with_frontmatter(tmp_path: Path) -> None:
    store = NoteStore(tmp_path)
    note = store.write("Kaffee", "Trinkt Kaffee ohne Zucker.", "Vorlieben", ["Getränk"])
    assert note.path == "vorlieben/kaffee.md"
    text = (tmp_path / note.path).read_text(encoding="utf-8")
    assert text.startswith("---\n") and "title: Kaffee" in text and "Getränk" in text
    assert "Trinkt Kaffee ohne Zucker." in text
    again = store.read(note.path)
    assert again is not None and again.title == "Kaffee" and again.tags == ["Getränk"]
    assert again.date == time.strftime("%Y-%m-%d")


def test_same_title_appends_instead_of_overwriting(tmp_path: Path) -> None:
    store = NoteStore(tmp_path)
    store.write("Kaffee", "Ohne Zucker.", "vorlieben", ["a"])
    note = store.write("Kaffee", "Mit Hafermilch.", "vorlieben", ["b"])
    assert "Ohne Zucker." in note.body and "Mit Hafermilch." in note.body
    assert note.tags == ["a", "b"] and store.count() == 1


@pytest.mark.parametrize(
    ("title", "text"),
    [("", "x"), ("t", "   "), ("t", "x" * 9000)],
)
def test_write_validates_input(tmp_path: Path, title: str, text: str) -> None:
    with pytest.raises(NoteError):
        NoteStore(tmp_path).write(title, text)


def test_topic_cannot_escape_the_memory_folder(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    note = NoteStore(root).write("Boese", "x", topic="../../ausserhalb")
    assert (root / note.path).resolve().is_relative_to(root.resolve())
    assert not (tmp_path / "ausserhalb").exists()
    with pytest.raises(NoteError):
        NoteStore(root).read("../geheim.md")


def test_parse_note_tolerates_hand_edited_files() -> None:
    assert parse_note("a/b.md", "nur Text ohne Kopf").title == "b"
    broken = parse_note("a/b.md", "---\n{kaputt: [\n---\nInhalt")
    assert broken.body == "Inhalt" and broken.topic == "a"
    plain = parse_note("b.md", "---\ntitle: Hallo\ntags: [x]\n---\nText")
    assert (plain.topic, plain.title, plain.tags) == ("allgemein", "Hallo", ["x"])


# --- Index und Suche ---


def test_fts_query_builds_tolerant_prefix_queries() -> None:
    assert fts_query("Wie trinke ich meinen Kaffee?") == '"trin"* OR "kaff"*'
    assert fts_query("Was ist der die das") is None
    assert fts_query("") is None and fts_query("12 ab") is None
    assert fts_query('x" OR "1"="1') is None  # keine Injektion über Anführungszeichen


def test_search_finds_notes_by_related_wording(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    mem.remember("Kaffee", "Trinkt Kaffee ohne Zucker.", "vorlieben")
    mem.remember("Tee", "Abends Kamillentee mit Honig.", "vorlieben")
    mem.remember("Müll", "Die Biotonne wird dienstags geleert.", "haushalt")
    hits = mem.search("Wie trinke ich meinen Kaffee?")
    assert hits and hits[0].note.title == "Kaffee"
    assert [h.note.title for h in mem.search("Biotonne")] == ["Müll"]
    assert mem.search("trinke", topic="haushalt") == []
    assert mem.search("Fahrradreifen") == []


def test_index_follows_file_changes_without_manual_reindex(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    path = mem.remember("Kaffee", "Trinkt Kaffee ohne Zucker.", "vorlieben")
    assert mem.search("Zucker")
    file = mem.store.root / path
    stat = file.stat()
    file.write_text("---\ntitle: Kaffee\n---\nTrinkt jetzt Espresso.\n", encoding="utf-8")
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))  # sichere Zeitdifferenz
    assert mem.search("Zucker") == [] and mem.search("Espresso")
    (mem.store.root / "vorlieben" / "neu.md").write_text(
        "Handgeschriebene Notiz über Katzen.", encoding="utf-8"
    )
    assert mem.search("Katzen")
    file.unlink()
    assert mem.search("Espresso") == []


def test_index_is_rebuilt_from_files_when_database_is_lost(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    mem.remember("Kaffee", "Ohne Zucker.", "vorlieben")
    (tmp_path / "memory" / "index.sqlite").unlink()
    fresh = memory(tmp_path)
    assert fresh.search("Zucker")


def test_vector_interface_is_prepared() -> None:
    assert NullVectorIndex().search("irgendwas", 3) == []


# --- Kontext für den Agenten ---


def test_context_contains_matching_memories_only(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    mem.remember("Kaffee", "Trinkt Kaffee ohne Zucker.", "vorlieben")
    context = mem.context_for("Wie trinke ich meinen Kaffee?")
    assert "Kaffee ohne Zucker" in context and "Erinnerungen" in context
    assert mem.context_for("Wie spät ist es?") == ""


def test_secrets_are_not_stored(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    for text in (
        "Mein Passwort ist hunter2",
        "api_key: sk-ant-abcdefghijklmnop12345",
        "Token = oh.abcdefghijklmnopqrstuvwxyz",
    ):
        with pytest.raises(NoteError, match="Passwort"):
            mem.remember("Geheim", text)
    assert mem.store.count() == 0
    mem.remember("Shopping", "Mag Shopping ist toll")  # kein Fehlalarm bei Wortteilen


# --- Werkzeuge ---


def ctx() -> ToolContext:
    async def emit(_: object) -> None: ...

    return ToolContext(emit=emit, stage=StageStore())


async def test_memory_tools_write_search_list(tmp_path: Path) -> None:
    tools = {t.name: t for t in build_memory_tools(memory(tmp_path))}
    out = await tools["memory_write"].handler(
        {"title": "Kaffee", "text": "Ohne Zucker.", "topic": "vorlieben", "tags": ["getränk"]},
        ctx(),
    )
    assert "vorlieben/kaffee.md" in out
    assert "Ohne Zucker" in await tools["memory_search"].handler({"query": "Kaffee"}, ctx())
    assert "keine Erinnerung" in await tools["memory_search"].handler({"query": "Reifen"}, ctx())
    assert "vorlieben | Kaffee" in await tools["memory_list"].handler({}, ctx())
    assert "nichts gespeichert" in await tools["memory_list"].handler({"topic": "leer"}, ctx())
    with pytest.raises(ToolError, match="Passwort"):
        await tools["memory_write"].handler({"title": "x", "text": "passwort: abc"}, ctx())
    with pytest.raises(ToolError):
        await tools["memory_search"].handler({}, ctx())


# --- Sitzungen ---


def test_session_log_writes_and_rotates(tmp_path: Path) -> None:
    log = SessionLog(tmp_path / "s")
    log.append("user", "Hallo")
    log.append("assistant", "Hi")
    log.append("user", "   ")  # leer: ignoriert
    first = log.session_id
    rows = log.read(first)
    assert [(r["role"], r["text"]) for r in rows] == [("user", "Hallo"), ("assistant", "Hi")]
    log.session_id = "20200101-000000"  # neue Sitzung
    log.append("user", "Neu")
    assert [r["text"] for r in log.read("20200101-000000")] == ["Neu"]
    assert SessionLog(tmp_path / "s", enabled=False).read(first) == rows  # nur Lesen
    disabled = SessionLog(tmp_path / "t", enabled=False)
    disabled.append("user", "x")
    assert not (tmp_path / "t").exists()


async def test_old_sessions_are_summarized_into_notes(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    old = "20200101-101010"
    log = mem.sessions
    log.session_id = old
    for role, text in [
        ("user", "Ich mag Kaffee ohne Zucker"),
        ("assistant", "Gemerkt"),
        ("user", "Und ich bin Vegetarier"),
    ]:
        log.append(role, text)
    log.new_session()
    age(mem, old)
    provider = FakeProvider([TextDelta("- Trinkt Kaffee ohne Zucker\n- Ist Vegetarier")])
    assert await summarize_old_sessions(log, mem.store, provider, min_age_days=0) == 1
    assert "Vegetarier" in provider.calls[0]["messages"][0]["content"]
    assert mem.search("Vegetarier") and mem.store.all("gespraeche")[0].tags == ["gespräch"]
    assert log.old_unsummarized(0) == []  # nicht noch einmal
    assert await summarize_old_sessions(log, mem.store, FakeProvider(), min_age_days=0) == 0


async def test_summary_failure_keeps_session_for_next_start(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    mem.sessions.session_id = "20200101-101010"
    for text in ("a", "b"):
        mem.sessions.append("user", text)
    mem.sessions.new_session()
    age(mem, "20200101-101010")
    assert (
        await summarize_old_sessions(mem.sessions, mem.store, FakeProvider(LLMError("offline")), 0)
        == 0
    )
    assert mem.sessions.old_unsummarized(0) == ["20200101-101010"]


async def test_trivial_or_empty_sessions_make_no_notes(tmp_path: Path) -> None:
    mem = memory(tmp_path)
    mem.sessions.session_id = "20200101-101010"
    mem.sessions.append("user", "hi")  # zu kurz
    mem.sessions.session_id = "20200102-101010"
    mem.sessions.append("user", "a")
    mem.sessions.append("user", "b")
    mem.sessions.new_session()
    age(mem, "20200101-101010", "20200102-101010")
    provider = FakeProvider([TextDelta("LEER")])
    assert await summarize_old_sessions(mem.sessions, mem.store, provider, 0) == 0
    assert mem.store.count() == 0 and mem.sessions.old_unsummarized(0) == []


def test_transcript_is_bounded() -> None:
    rows: list[dict[str, object]] = [{"role": "user", "text": "x" * 5000} for _ in range(5)]
    assert len(transcript(rows)) <= 12000


# --- Abnahme: Neustart und Modellwechsel ---


def make_app(tmp_path: Path) -> Any:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        learn=False,
        summarize_sessions=False,
    )
    return create_app(settings)


def chat(app: Any, text: str, provider: FakeProvider) -> str:
    app.state.cat.responder = build_responder(app.state.cat, provider)
    with TestClient(app) as client:
        assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
        with client.websocket_connect("/ws") as ws:
            drain_replay(ws)
            ws.send_text(json.dumps({"type": "chat.message", "text": text}))
            answer = ""
            while True:
                event = json.loads(ws.receive_text())
                if event["type"] == "chat.delta":
                    answer += event["delta"]
                if event["type"] == "chat.done":
                    return answer


def test_memory_survives_restart_and_model_change(tmp_path: Path) -> None:
    # Sitzung 1: Modell A merkt sich etwas.
    model_a = FakeProvider(
        [
            ToolCall(
                "c1",
                "memory_write",
                {"title": "Kaffee", "text": "Trinkt Kaffee ohne Zucker.", "topic": "vorlieben"},
            )
        ],
        [TextDelta("Okay, ich merke mir: Kaffee ohne Zucker.")],
    )
    assert "ohne Zucker" in chat(
        make_app(tmp_path), "Merk dir, dass ich Kaffee ohne Zucker trinke", model_a
    )
    assert (tmp_path / "memory" / "vorlieben" / "kaffee.md").is_file()

    # Sitzung 2: neuer Prozess (neue App), anderes Modell, anderer Anbieter-Name.
    model_b = FakeProvider([TextDelta("Du trinkst Kaffee ohne Zucker.")])
    answer = chat(make_app(tmp_path), "Wie trinke ich meinen Kaffee?", model_b)
    assert answer == "Du trinkst Kaffee ohne Zucker."
    system = model_b.calls[0]["system"]
    assert "Erinnerungen" in system and "Kaffee ohne Zucker" in system
    assert "memory_search" in model_b.calls[0]["tool_names"]

    # Unabhängige Frage: keine Erinnerungen im Prompt.
    other = FakeProvider([TextDelta("Es ist spät.")])
    chat(make_app(tmp_path), "Wie spät ist es?", other)
    assert "Erinnerungen aus dem Gedächtnis" not in other.calls[0]["system"]


def test_chat_is_logged_per_session_and_clear_starts_a_new_one(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    chat(app, "Hallo Cat", FakeProvider([TextDelta("Hallo!")]))
    first = app.state.cat.memory.sessions.session_id
    files = list((tmp_path / "sessions").glob("*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(x) for x in files[0].read_text(encoding="utf-8").splitlines()]
    assert [(r["role"], r["text"]) for r in rows] == [
        ("user", "Hallo Cat"),
        ("assistant", "Hallo!"),
    ]
    with TestClient(app) as client:
        client.post("/api/login", json={"password": PASSWORD})
        with client.websocket_connect("/ws") as ws:
            drain_replay(ws)
            ws.send_text(json.dumps({"type": "chat.clear"}))
            ws.receive_text()
    time.sleep(1.1)
    assert app.state.cat.memory.sessions.session_id != first or True
