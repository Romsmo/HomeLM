import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cat.config import Settings
from cat.llm.base import TextDelta, ToolCall
from cat.main import create_app
from cat.memory import knowledge
from cat.memory.notes import Note
from cat.memory.reflect import Reflector, build_prompt, looks_personal, parse_facts
from cat.memory.service import MemoryService
from cat.state import AppState
from tests.conftest import PASSWORD
from tests.test_router import FakeClaude, ok

# --- Wissens-Cache: was wird gemerkt ---


@pytest.mark.parametrize(
    "question",
    [
        "Wer hat Goethes Faust geschrieben?",
        "Wie funktioniert eine Wärmepumpe?",
        "Warum ist der Himmel blau?",
    ],
)
def test_timeless_general_questions_are_cacheable(question: str) -> None:
    assert knowledge.cacheable(question, "Eine ausreichend lange Antwort mit Inhalt.")


@pytest.mark.parametrize(
    "question",
    [
        "Wie wird das Wetter?",
        "Was kostet Gold heute?",
        "Wie ist der aktuelle Dollarkurs?",
        "Was mag ich zum Frühstück?",
        "Wer gewinnt gerade das Spiel?",
        "Hi",
    ],
)
def test_changing_or_personal_questions_are_not_cached(question: str) -> None:
    assert not knowledge.cacheable(question, "Eine ausreichend lange Antwort mit Inhalt.")


def test_answers_that_are_too_short_or_pages_are_not_cached() -> None:
    assert not knowledge.cacheable("Wer hat Faust geschrieben?", "Goethe.")
    assert not knowledge.cacheable("Zeig mir eine Uhr aus HTML", "x" * 100, has_pages=True)


def make_service(tmp_path: Path) -> MemoryService:
    return MemoryService(tmp_path / "memory", tmp_path / "sessions")


def test_a_cached_answer_is_found_again_and_a_new_one_replaces_it(tmp_path: Path) -> None:
    memory = make_service(tmp_path)
    assert memory.remember_answer(
        "Wer hat Goethes Faust geschrieben?", "Johann Wolfgang von Goethe schrieb den Faust."
    )
    cached = memory.cached_answer("wer hat goethes faust geschrieben")
    assert cached is not None and "Goethe" in cached.answer and cached.date
    assert memory.cached_answer("Wie funktioniert ein Kühlschrank?") is None
    memory.remember_answer("Wer hat Goethes Faust geschrieben?", "Goethe, 1808 erschien Teil 1.")
    again = memory.cached_answer("Wer hat Goethes Faust geschrieben?")
    assert again is not None and "1808" in again.answer and "Wolfgang" not in again.answer
    assert len(memory.store.all(knowledge.TOPIC)) == 1


def test_old_cached_answers_are_not_used(tmp_path: Path) -> None:
    old = time.strftime("%Y-%m-%d", time.localtime(time.time() - 400 * 86400))
    note = Note("wissen/x.md", "wissen", "Wer hat Faust geschrieben", old, [], "Antwort: Goethe.")
    assert knowledge.matches("Wer hat Faust geschrieben?", note) is None


def test_forget_deletes_one_note_and_asks_when_unclear(tmp_path: Path) -> None:
    memory = make_service(tmp_path)
    memory.remember("Kaffee", "Der Nutzer trinkt Kaffee mit Hafermilch.", "vorlieben")
    memory.remember("Tee", "Der Nutzer trinkt abends Tee mit Honig.", "vorlieben")
    assert "keine Notiz" in memory.forget("Fußball")
    assert "mehreren" in memory.forget("trinkt")  # passt zu beiden
    assert memory.forget("Kaffee Hafermilch") == "Vergessen: Kaffee."
    assert [n.title for n in memory.store.all()] == ["Tee"]
    assert memory.search("Kaffee") == []  # auch aus dem Index


def test_notes_cannot_be_deleted_outside_the_memory_folder(tmp_path: Path) -> None:
    from cat.memory.notes import NoteError

    (tmp_path / "geheim.md").write_text("x", encoding="utf-8")
    memory = make_service(tmp_path)
    with pytest.raises(NoteError):
        memory.store.delete("../geheim.md")
    assert (tmp_path / "geheim.md").exists()


# --- Selbst lernen ---


@pytest.mark.parametrize(
    "text",
    [
        "Ich trinke morgens immer Kaffee mit Hafermilch.",
        "Meine Tochter heißt Lena und mag Katzen.",
        "Ich bin allergisch gegen Nüsse.",
    ],
)
def test_personal_statements_are_noticed(text: str) -> None:
    assert looks_personal(text)


@pytest.mark.parametrize(
    "text",
    [
        "Mach das Licht aus",
        "Welche Rollos sind offen?",
        "Ich möchte das Licht im Büro an",  # Gerät: kein Fakt
        "Wie spät ist es?",
        "ok",
    ],
)
def test_questions_commands_and_chatter_are_not_facts(text: str) -> None:
    assert not looks_personal(text, device_related="Licht" in text)


def test_facts_are_parsed_tolerantly_and_checked() -> None:
    output = (
        'Hier die Fakten: [{"title": "Kaffee", "text": "Der Nutzer trinkt morgens Kaffee '
        'mit Hafermilch.", "topic": "gewohnheiten"}, {"title": "Ich", "text": "Ich mag Tee '
        'sehr gerne.", "topic": "vorlieben"}, {"title": "Kurz", "text": "Zu kurz"}, 5]'
    )
    facts = parse_facts(output)
    assert [(f.title, f.topic) for f in facts] == [
        ("Kaffee", "gewohnheiten")
    ]  # Ich-Form fällt raus
    assert parse_facts("kein JSON") == [] and parse_facts("[] ") == []
    assert "Der Nutzer" in build_prompt(["Ich mag Tee."]) and "Passwörter" in build_prompt(["x"])


async def test_reflection_saves_facts_only_when_idle_and_returns_the_queue_on_errors() -> None:
    reflector = Reflector(idle_s=60)
    assert reflector.observe("Ich trinke morgens immer Kaffee mit Hafermilch.")
    assert not reflector.observe("Mach das Licht an")
    saved: list[str] = []

    async def save(fact, speaker):  # type: ignore[no-untyped-def]
        saved.append(f"{speaker}:{fact.title}")
        return True

    async def generate(_: str) -> str:
        return '[{"title": "Kaffee", "text": "Der Nutzer trinkt Kaffee mit Hafermilch."}]'

    now = time.monotonic()
    assert await reflector.run_once(generate, save, now, busy=False) == []  # gerade aktiv
    assert await reflector.run_once(generate, save, now - 120, busy=True) == []  # beschäftigt
    assert reflector.pending == 1
    facts = await reflector.run_once(generate, save, now - 120, busy=False)
    assert [f.title for f in facts] == ["Kaffee"] and saved == ["None:Kaffee"]

    reflector.observe("Meine Tochter heißt Lena.")

    async def broken(_: str) -> str:
        raise RuntimeError("Ollama aus")

    assert await reflector.run_once(broken, save, now - 120, busy=False) == []
    assert reflector.pending == 1  # nicht verloren, später wieder


async def test_save_fact_writes_a_note_and_tells_the_user(tmp_path: Path) -> None:
    from cat.memory.reflect import Fact

    state = AppState(Settings(_env_file=None, data_dir=tmp_path, plugins=""))  # type: ignore[call-arg]
    sent: list = []

    async def emit(event) -> None:  # type: ignore[no-untyped-def]
        sent.append(event)

    state.emit = emit  # type: ignore[method-assign]
    await state.save_fact(Fact("Kaffee", "Der Nutzer trinkt Kaffee mit Hafermilch.", "vorlieben"))
    note = state.memory.store.read("vorlieben/kaffee.md")
    assert note is not None and "auto" in note.tags
    assert "vergiss Kaffee" in sent[0].text and sent[0].role == "system"


# --- Wissens-Cache im Router ---


async def test_the_same_question_is_answered_from_memory_without_claude(tmp_path: Path) -> None:
    from tests.fakes import FakeProvider
    from tests.test_router import Env

    claude = FakeClaude(ok("Johann Wolfgang von Goethe hat den Faust geschrieben, ab 1772."))
    env = Env(
        tmp_path, FakeProvider([ToolCall("c", "ask_claude", {"question": "x"})] * 1), claude, 5
    )
    first = await env.ask("Frag Claude: Wer hat Goethes Faust geschrieben?")
    assert "Goethe" in first and len(claude.prompts) == 1 and env.budget.used_today == 1
    # Dieselbe Frage ohne ausdrückliche Weitergabe: Antwort aus dem Gedächtnis, kein zweiter Aufruf.
    env.responder._state.chat.clear()  # type: ignore[attr-defined]
    again = await env.ask("Wer hat Goethes Faust geschrieben?")
    assert "Goethe" in again and "Aus dem Gedächtnis" in again
    assert len(claude.prompts) == 1 and env.budget.used_today == 1
    assert env.provider.calls == []  # auch das lokale Modell wurde nicht gefragt
    spoken = await env.ask("Wer hat Goethes Faust geschrieben?", spoken=True)
    assert "Goethe" in spoken and "Gedächtnis" not in spoken  # gesprochen: ohne Hinweis
    # Ausdrücklich Claude verlangt: immer frisch (hier ohne weitere Antwort in FakeClaude).
    assert knowledge.TOPIC in {n.topic for n in env.state.memory.store.all()}


# --- HTTP ---


def test_notes_can_be_listed_and_deleted_over_http(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        learn=False,
        summarize_sessions=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/api/memory").status_code == 401
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        app.state.cat.memory.remember("Kaffee", "Der Nutzer trinkt Kaffee.", "vorlieben")
        rows = c.get("/api/memory").json()
        assert rows[0]["title"] == "Kaffee" and rows[0]["path"] == "vorlieben/kaffee.md"
        assert c.delete("/api/memory", params={"path": "../x.md"}).status_code in (400, 404)
        assert c.delete("/api/memory", params={"path": "vorlieben/kaffee.md"}).status_code == 200
        assert c.get("/api/memory").json() == []
        assert c.delete("/api/memory", params={"path": "vorlieben/kaffee.md"}).status_code == 404
        assert TextDelta  # Import wird für die Tests oben gebraucht


def test_learned_shortcuts_are_exported_as_a_readable_note(tmp_path: Path) -> None:
    state = AppState(Settings(_env_file=None, data_dir=tmp_path, plugins=""))  # type: ignore[call-arg]
    state.learner.listing = lambda: [  # type: ignore[method-assign]
        {"phrase": "ist das {dev} an", "does": "Zustand lesen", "active": True},
        {"phrase": "noch nicht", "does": "x", "active": False},
    ]
    state.export_learned()
    state.export_learned()  # zweimal: ersetzt, hängt nicht an
    note = state.memory.store.read("gelerntes/kurzbefehle.md")
    assert note is not None and note.body.count("ist das {dev} an") == 1
    assert "noch nicht" not in note.body


async def test_background_generation_stops_as_soon_as_the_user_does_something(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cat import main as main_module

    state = AppState(Settings(_env_file=None, data_dir=tmp_path, plugins=""))  # type: ignore[call-arg]
    closed: list[bool] = []
    calls = {"n": 0}

    class Provider:
        async def stream(self, system, messages, tools):  # type: ignore[no-untyped-def]
            try:
                calls["n"] += 1
                yield TextDelta("Hallo ")
                if calls["n"] == 1:
                    state.touch()  # der Nutzer beginnt zu sprechen
                yield TextDelta("Welt")
            finally:
                closed.append(True)

    monkeypatch.setattr(main_module, "build_local_provider", lambda _: Provider())
    generate = main_module._local_generate(state)
    with pytest.raises(RuntimeError, match="unterbrochen"):
        await generate("Schreib etwas")
    assert closed == [True]  # die Verbindung zu Ollama wurde geschlossen

    calm = await generate("Und jetzt in Ruhe")  # ohne Unterbrechung läuft sie durch
    assert calm == "Hallo Welt"


async def test_background_generation_rewarms_the_main_prompt_afterwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cat import main as main_module

    state = AppState(Settings(_env_file=None, data_dir=tmp_path, plugins=""))  # type: ignore[call-arg]
    warmed: list[bool] = []

    class Responder:
        async def warm(self) -> None:
            warmed.append(True)

    state.responder = Responder()  # type: ignore[assignment]

    class Provider:
        async def stream(self, system, messages, tools):  # type: ignore[no-untyped-def]
            yield TextDelta("Fertig")

    monkeypatch.setattr(main_module, "build_local_provider", lambda _: Provider())
    assert await main_module._local_generate(state)("x") == "Fertig"
    assert warmed == [True]  # Cats Prompt wird nach der Hintergrundaufgabe neu vorgewärmt


async def test_a_quick_second_message_waits_for_the_lock_instead_of_failing(
    tmp_path: Path,
) -> None:
    import asyncio

    from cat.dialog import handle_user_text

    state = AppState(Settings(_env_file=None, data_dir=tmp_path, plugins=""))  # type: ignore[call-arg]

    async def emit(_: object) -> None: ...

    state.emit = emit  # type: ignore[method-assign]
    await state.run_lock.acquire()
    asyncio.get_running_loop().call_later(0.1, state.run_lock.release)
    reply = await handle_user_text(state, "Hallo")  # kein wait=True: trotzdem kein Fehler
    assert reply.text.startswith("Echo: Hallo")


def test_lexicon_terms_can_be_listed_and_deleted_over_http(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
        learn=False,
        summarize_sessions=False,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/api/lexicon").status_code == 401
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        app.state.cat.lexicon.add("Dach-Rollo", ["unbekannt"])
        rows = c.get("/api/lexicon").json()
        assert rows[0]["term"] == "Dach-Rollo" and rows[0]["devices"] == []
        assert c.delete("/api/lexicon", params={"term": "Dachrollos"}).status_code == 200
        assert c.get("/api/lexicon").json() == []
        assert c.delete("/api/lexicon", params={"term": "Dachrollos"}).status_code == 404
