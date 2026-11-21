"""Natürlichere Antworten: kurz, zusammengefasst, nicht mitten im Befehl nach dem Namen fragen."""

from collections.abc import AsyncIterator
from pathlib import Path

from cat.config import Settings
from cat.devices.models import DeviceSpec
from cat.dialog import handle_user_text
from cat.intents.replies import confirm_many, join_names
from cat.state import AppState
from cat.ws.protocol import ChatMessage
from tests.test_context import teach_for
from tests.test_markisen import Setup, awning_items


def spec(name: str, type_: str = "shutter", room: str = "Terrasse") -> DeviceSpec:
    return DeviceSpec(
        id=name.lower().replace(" ", "_"),
        backend="openhab",
        item=name.replace(" ", "_"),
        name=name,
        room=room,
        type=type_,  # type: ignore[arg-type]
    )


def test_names_share_the_first_word_once() -> None:
    assert (
        join_names(["Markise Nord", "Markise Ost", "Markise West"]) == "Markise Nord, Ost und West"
    )
    assert join_names(["Romans Rollo", "Marius Rollo"]) == "Romans Rollo und Marius Rollo"
    assert join_names(["Markise Nord"]) == "Markise Nord"
    assert join_names(["Licht", "Markise Ost"]) == "Licht und Markise Ost"


def test_equal_commands_are_merged_and_different_ones_stay_apart() -> None:
    nord, ost, west = spec("Markise Nord"), spec("Markise Ost"), spec("Markise West")
    assert confirm_many([(nord, "down"), (ost, "down"), (west, "down")]) == [
        "Okay, Markise Nord, Ost und West fahren runter."
    ]
    assert confirm_many([(nord, "up")]) == ["Okay, Markise Nord fährt hoch."]
    assert confirm_many([(nord, "up"), (ost, "down")]) == [
        "Okay, Markise Nord fährt hoch.",
        "Okay, Markise Ost fährt runter.",
    ]
    assert confirm_many([(nord, "0"), (ost, "0")]) == ["Okay, Markise Nord und Ost sind offen."]
    assert confirm_many([(nord, "100"), (ost, "100")]) == ["Okay, Markise Nord und Ost sind zu."]
    assert confirm_many([(nord, "40"), (ost, "40")]) == [
        "Okay, Markise Nord und Ost sind zu 40 Prozent geschlossen."
    ]
    lamp = spec("Lampe", "light", "Bad")
    assert confirm_many([(lamp, "on"), (spec("Licht", "switch", "Bad"), "on")]) == [
        "Okay, Lampe und Licht sind an."
    ]


async def test_asking_for_the_awnings_answers_in_one_sentence(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    out = await s.get_state({"device": "Markisen"}, s.ctx("Wie sind die Markisen?"))
    assert out == "Markise Nord, Ost und West sind alle offen."  # nicht der Sensor "... Manuell"


async def test_and_east_asks_about_the_same_kind(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    await s.get_state({"device": "Markise Nord"}, s.ctx("Ist Markise Nord offen?"))
    assert await teach.intercept("Und Ost?") == "Markise Ost ist offen."
    assert await teach.intercept("Und West?") == "Markise West ist offen."
    assert await teach.intercept("Und Süd?") is None  # unbekannt: nicht raten
    assert s.backend.sent == []  # gelesen, nie geschaltet


async def test_and_east_without_context_goes_to_the_model(tmp_path: Path) -> None:
    s = Setup(tmp_path, awning_items())
    teach = teach_for(s, tmp_path)
    assert await teach.intercept("Und Ost?") is None


# --- Namensfrage nicht mitten im Befehl ---


class ToolResponder:
    """Antwortet wie nach einem Werkzeugaufruf (state.turn_tooled) oder ohne."""

    def __init__(self, state: AppState, tooled: bool) -> None:
        self._state = state
        self._tooled = tooled

    async def reply(
        self, history: list[ChatMessage], spoken: bool = False, room: str | None = None
    ) -> AsyncIterator[str]:
        self._state.turn_tooled = self._tooled
        yield "Okay, erledigt."


def people_state(tmp_path: Path) -> AppState:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, data_dir=tmp_path, plugins="", learn=False, people=True, filler=False
    )
    state = AppState(settings)

    async def emit(_: object) -> None: ...

    state.emit = emit  # type: ignore[method-assign]
    return state


async def test_the_name_is_not_asked_right_after_a_command(tmp_path: Path) -> None:
    state = people_state(tmp_path)
    state.responder = ToolResponder(state, tooled=True)  # type: ignore[assignment]
    reply = await handle_user_text(state, "Mach das Licht an")
    assert "Wie heißt du" not in reply.text  # früher: "Übrigens, mit wem spreche ich ...?"

    state.responder = ToolResponder(state, tooled=False)  # type: ignore[assignment]
    later = await handle_user_text(state, "Erzähl mir was")
    assert later.text.endswith("Wie heißt du?")  # in einem ruhigen Moment dagegen schon
