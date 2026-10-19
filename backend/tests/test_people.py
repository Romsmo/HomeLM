import math
import os
import stat
from pathlib import Path

import pytest

from cat.config import Settings
from cat.dialog import handle_user_text
from cat.people.parse import (
    DECLINE,
    parse_name,
    parse_yes_no,
    wants_person_forgotten,
    wants_voice_forgotten,
)
from cat.people.service import PeopleService
from cat.people.store import PeopleStore
from cat.state import AppState
from cat.voice.speaker import cosine

# --- Namen und Ja/Nein ---


@pytest.mark.parametrize(
    ("text", "asked", "expected"),
    [
        ("Roman", True, "Roman"),
        ("ich bin lena", True, "Lena"),
        ("Ich heiße Anna-Lena.", True, "Anna-Lena"),
        ("Mein Name ist Max Mustermann", True, "Max Mustermann"),
        ("Hier ist Roman übrigens", True, "Roman"),
        ("Ich heiße Roman", False, "Roman"),  # ausdrückliche Vorstellung ohne Frage
        ("mein name ist lena", False, "Lena"),
        ("Ich bin Roman", False, None),  # ohne Frage zu unsicher ("Ich bin müde")
        ("Ich bin müde", True, None),
        ("Danke", True, None),
        ("ja", True, None),
        ("Das ist aber eine lange Antwort ohne Namen", True, None),
        ("Nein, lieber nicht", True, DECLINE),
        ("", True, None),
    ],
)
def test_names_are_read_from_short_answers(text: str, asked: bool, expected: str | None) -> None:
    assert parse_name(text, asked=asked) == expected


def test_yes_no_and_forget_commands() -> None:
    assert parse_yes_no("Ja, gerne") is True and parse_yes_no("nein danke") is False
    assert parse_yes_no("vielleicht") is None
    assert wants_voice_forgotten("Vergiss meine Stimme bitte")
    assert wants_person_forgotten("vergiss mich")
    assert not wants_voice_forgotten("Vergiss, dass ich Kaffee mag")


# --- Speicher ---


def vec(*parts: float, size: int = 8) -> list[float]:
    raw = [*parts, *([0.0] * (size - len(parts)))]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def test_store_persists_privately_and_finds_names_loosely(tmp_path: Path) -> None:
    path = tmp_path / "people.json"
    store = PeopleStore(path)
    roman = store.add("Roman")
    roman.consent_voice = True
    store.add_embedding(roman, vec(1))
    again = PeopleStore(path)
    assert again.find_by_name("roman").id == roman.id  # type: ignore[union-attr]
    assert again.find_by_name("Romann") is not None and again.find_by_name("Lena") is None
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert again.get(roman.id).embeddings == [vec(1)]  # type: ignore[union-attr]


def test_embeddings_need_consent_and_are_capped(tmp_path: Path) -> None:
    store = PeopleStore(tmp_path / "p.json")
    person = store.add("Lena")
    store.add_embedding(person, vec(1))
    assert person.embeddings == []  # ohne Zustimmung nichts speichern
    person.consent_voice = True
    for i in range(12):
        store.add_embedding(person, vec(1, i / 10))
    assert len(person.embeddings) == 8
    store.forget_voice(person.id)
    assert person.embeddings == [] and not person.consent_voice


def test_match_returns_best_and_runner_up(tmp_path: Path) -> None:
    store = PeopleStore(tmp_path / "p.json")
    for name, v in (("Roman", vec(1, 0.1)), ("Lena", vec(0, 1))):
        person = store.add(name)
        person.consent_voice = True
        store.add_embedding(person, v)
    match = store.match(vec(1, 0.2))
    assert match.person is not None and match.person.name == "Roman"
    assert match.score > 0.9 and match.runner_up < 0.4
    assert store.match(vec(0, 0, 0, 1)).score < 0.2
    assert cosine(vec(1), vec(1)) == pytest.approx(1.0)


# --- Ablauf ---


class Encoder:
    """Der erste Byte der Äußerung wählt die "Stimme"."""

    voices = {
        0: vec(1, 0.05),  # Roman
        1: vec(0, 1),  # Lena
        2: vec(1, 1.8),  # klingt nach Roman, aber nicht sicher
        3: vec(0, 0, 0, 1),  # niemand
    }

    def embed(self, pcm: bytes) -> list[float] | None:
        return self.voices[pcm[0]] if len(pcm) > 1 else None


def pcm(voice: int) -> bytes:
    return bytes([voice]) * 32


def make(tmp_path: Path, *, with_encoder: bool = True) -> PeopleService:
    service = PeopleService(
        PeopleStore(tmp_path / "people.json"),
        is_request=lambda text: "licht" in text.lower() or text.endswith("?"),
    )
    if with_encoder:
        service.encoder = Encoder()
    return service


KEY = "voice:a"


async def hear(service: PeopleService, voice: int, text: str, key: str = KEY):  # type: ignore[no-untyped-def]
    """Eine Äußerung: erkennen, Antwort auf offene Frage, sonst Folgefrage zur Antwort."""
    identity = await service.identify_voice(key, pcm(voice))
    reply = await service.intercept(key, text)
    follow = None if reply is not None else service.follow_up(key, identity)
    return identity, reply, follow


async def test_unknown_voice_is_asked_for_a_name_after_the_answer(tmp_path: Path) -> None:
    service = make(tmp_path)
    identity, reply, follow = await hear(service, 0, "Mach das Licht an")
    assert identity.status == "unknown" and reply is None
    assert follow == "Übrigens, ich kenne deine Stimme noch nicht. Wie heißt du?"
    _, reply, _ = await hear(service, 0, "Roman")
    assert reply is not None and "Darf ich mir deine Stimme merken" in reply
    assert [p.name for p in service.store.all()] == ["Roman"]
    assert service.store.all()[0].embeddings == []  # noch ohne Zustimmung nichts gespeichert


async def test_voice_is_stored_only_after_yes_and_then_recognised(tmp_path: Path) -> None:
    service = make(tmp_path)
    await hear(service, 0, "Mach das Licht an")
    await hear(service, 0, "Roman")
    _, reply, _ = await hear(service, 0, "ja gerne")
    assert reply is not None and "merke mir deine Stimme" in reply
    roman = service.store.all()[0]
    assert roman.consent_voice and len(roman.embeddings) >= 1
    # Später, neue Sitzung: erkannt, begrüßt (einmal), kein Fragen mehr.
    identity, reply, follow = await hear(service, 0, "Mach das Licht aus", key="voice:b")
    assert identity.status == "known" and identity.person is not None
    assert identity.person.name == "Roman" and reply is None and follow is None
    assert service.speaker_for("voice:b").name == "Roman"  # type: ignore[union-attr]
    assert service.greeting("voice:b", identity) == "Hallo Roman! "
    assert service.greeting("voice:b", identity) is None


async def test_a_different_voice_is_not_taken_for_a_known_one(tmp_path: Path) -> None:
    service = make(tmp_path)
    for text in ("Mach das Licht an", "Roman", "ja"):
        await hear(service, 0, text)
    identity, _, follow = await hear(service, 1, "Mach das Licht aus", key="voice:b")
    assert identity.status == "unknown" and service.speaker_for("voice:b") is None
    assert follow is not None and "Wie heißt du" in follow


async def test_an_unsure_voice_is_confirmed_by_asking(tmp_path: Path) -> None:
    service = make(tmp_path)
    for text in ("Mach das Licht an", "Roman", "ja"):
        await hear(service, 0, text)
    identity, _, follow = await hear(service, 2, "Mach das Licht aus", key="voice:c")
    assert identity.status == "uncertain" and follow == "Bist du Roman?"
    _, reply, _ = await hear(service, 2, "ja", key="voice:c")
    assert reply == "Schön, Roman."
    assert service.speaker_for("voice:c").name == "Roman"  # type: ignore[union-attr]


async def test_declining_the_name_stops_the_questions(tmp_path: Path) -> None:
    service = make(tmp_path)
    await hear(service, 0, "Mach das Licht an")
    _, reply, _ = await hear(service, 0, "nein lieber nicht")
    assert reply == "Alles klar, ich frage nicht weiter."
    _, _, follow = await hear(service, 0, "Mach das Licht aus")
    assert follow is None and service.store.all() == []


async def test_ignoring_the_question_with_a_request_is_fine(tmp_path: Path) -> None:
    service = make(tmp_path)
    await hear(service, 0, "Mach das Licht an")
    _, reply, _ = await hear(service, 0, "Mach das Licht aus")  # kein Name: normale Anfrage
    assert reply is None and service.store.all() == []


async def test_saying_no_to_the_voice_keeps_the_person_but_not_the_voice(tmp_path: Path) -> None:
    service = make(tmp_path)
    for text in ("Mach das Licht an", "Lena"):
        await hear(service, 1, text)
    _, reply, _ = await hear(service, 1, "nein")
    assert reply == "Okay, ich merke sie mir nicht."
    lena = service.store.all()[0]
    assert not lena.consent_voice and lena.embeddings == []
    assert service.speaker_for(KEY).name == "Lena"  # type: ignore[union-attr]


async def test_forgetting_the_voice_or_the_person(tmp_path: Path) -> None:
    gone: list[str] = []

    async def on_forget(person) -> None:  # type: ignore[no-untyped-def]
        gone.append(person.name)

    service = make(tmp_path)
    service._on_forget = on_forget
    for text in ("Mach das Licht an", "Roman", "ja"):
        await hear(service, 0, text)
    assert (
        await service.intercept(KEY, "Vergiss meine Stimme")
        == "Okay, ich habe deine Stimme vergessen."
    )
    assert service.store.all()[0].embeddings == []
    reply = await service.intercept(KEY, "Vergiss mich")
    assert reply is not None and "vergessen" in reply and gone == ["Roman"]
    assert service.store.all() == [] and service.speaker_for(KEY) is None
    assert "nicht, wessen" in (await service.intercept(KEY, "vergiss meine stimme") or "")


async def test_without_a_voice_model_the_chat_asks_for_the_name(tmp_path: Path) -> None:
    service = make(tmp_path, with_encoder=False)
    assert service.follow_up("chat", await service.identify_voice("chat", b"")) == (
        "Übrigens, mit wem spreche ich eigentlich? Wie heißt du?"
    )
    reply = await service.intercept("chat", "Ich bin Roman")
    assert reply == "Freut mich, Roman!" and service.speaker_for("chat").name == "Roman"  # type: ignore[union-attr]
    assert service.follow_up("chat", await service.identify_voice("chat", b"")) is None


async def test_chat_takes_over_whoever_was_just_recognised_by_voice(tmp_path: Path) -> None:
    service = make(tmp_path)
    for text in ("Mach das Licht an", "Roman", "ja"):
        await hear(service, 0, text)
    await hear(service, 0, "Mach das Licht aus", key="voice:b")
    assert service.speaker_for("chat").name == "Roman"  # type: ignore[union-attr]
    assert service.speaker_for("voice:fremd") is None  # fremde Sprachsitzung: nicht automatisch


async def test_an_explicit_introduction_works_without_a_question(tmp_path: Path) -> None:
    service = make(tmp_path, with_encoder=False)
    assert await service.intercept("chat", "Ich bin müde") is None
    assert await service.intercept("chat", "Mein Name ist Lena") == "Freut mich, Lena!"
    assert await service.intercept("chat", "Ich heiße lena") == "Hallo Lena, schön dich zu hören."


def test_context_line_names_the_speaker(tmp_path: Path) -> None:
    service = make(tmp_path)
    person = service.store.add("Roman")
    assert "Roman" in service.context_line(person) and service.context_line(None) == ""


# --- im Dialog ---


def people_state(tmp_path: Path) -> AppState:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, data_dir=tmp_path, plugins="", learn=False, people=True, filler=False
    )
    state = AppState(settings)

    async def emit(_: object) -> None: ...

    state.emit = emit  # type: ignore[method-assign]
    return state


async def test_chat_asks_once_then_remembers_the_name_and_the_notes_of_the_person(
    tmp_path: Path,
) -> None:
    state = people_state(tmp_path)
    first = await handle_user_text(state, "Hallo Welt")
    assert first.text.endswith("Wie heißt du?") and first.text.startswith("Echo: Hallo Welt")
    second = await handle_user_text(state, "Roman")
    assert second.text == "Freut mich, Roman!" and second.fastpath
    assert state.people.store.all()[0].name == "Roman"
    profile = state.memory.store.read("personen/roman.md")
    assert profile is not None and "gehört zum Haushalt" in profile.body
    third = await handle_user_text(state, "Und jetzt?")
    assert "Wie heißt du" not in third.text
    assert state.current_speaker is not None and state.current_speaker.name == "Roman"
    # Vorstellung wird nicht an das Modell oder ins Lernen gegeben, beide Nachrichten sind "tooled".
    assert [m.tooled for m in state.chat][2:4] == [True, True]


async def test_notes_of_the_speaker_come_first_in_the_context(tmp_path: Path) -> None:
    state = people_state(tmp_path)
    state.memory.remember(
        "Kaffee", "Roman trinkt Kaffee mit Hafermilch.", "vorlieben", ["auto", "Roman"]
    )
    state.memory.remember(
        "Kaffee Lena", "Lena trinkt Kaffee schwarz.", "vorlieben", ["auto", "Lena"]
    )
    context = state.memory.context_for("Wie trinke ich meinen Kaffee?", "Roman")
    assert context.index("Hafermilch") < context.index("schwarz")


async def test_forgetting_a_person_deletes_their_notes(tmp_path: Path) -> None:
    state = people_state(tmp_path)
    await handle_user_text(state, "Hallo")
    await handle_user_text(state, "Roman")
    state.memory.remember("Kaffee", "Roman trinkt Kaffee.", "vorlieben", ["auto", "Roman"])
    state.memory.remember("Tee", "Der Haushalt mag Tee.", "vorlieben", ["auto"])
    reply = await handle_user_text(state, "Vergiss mich")
    assert "vergessen" in reply.text and state.people.store.all() == []
    assert [n.title for n in state.memory.store.all()] == ["Tee"]
