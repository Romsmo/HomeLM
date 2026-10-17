"""Ende zu Ende: echter Server (uvicorn) + der echte Satelliten-Code mit simuliertem Audio."""

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml

from cat.config import Settings
from cat.devices.models import DeviceSpec
from cat.devices.service import RawState
from cat.main import create_app
from cat.satellites import SatelliteRegistry, hash_token
from tests.conftest import PASSWORD
from tests.test_voice import FakeStt, make_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "satellite"))
from cat_satellite.client import AuthRejected, Mode, Satellite  # noqa: E402
from cat_satellite.config import parse_config  # noqa: E402

TOKEN_KUECHE = "k" * 40
TOKEN_FLUR = "f" * 40

DEVICES = """
devices:
  - {id: kuechenlicht, backend: openhab, item: KL, name: Küchenlicht, room: Küche, type: light}
  - {id: flurlicht, backend: openhab, item: FL, name: Flurlicht, room: Flur, type: light}
"""


class Backend:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def read(self, spec: DeviceSpec) -> RawState:
        return RawState("OFF")

    async def send(self, spec: DeviceSpec, command: str) -> None:
        self.sent.append((spec.id, command))


class FakeMic:
    """Erst Wake-Word, dann ein Strom von Sprachblöcken (die Fake-VAD entscheidet)."""

    def __init__(self, speech_frames: int = 24) -> None:
        self.speech_frames = speech_frames
        self.active = False

    async def frames(self):  # type: ignore[no-untyped-def]
        sent_wake = False
        speech = 0
        while True:
            await asyncio.sleep(0.01)
            if not sent_wake:
                sent_wake = True
                yield b"WAKE"
            elif self.active and speech < self.speech_frames:
                speech += 1
                yield b"\x01\x00" * 1280
            else:
                yield b"\x00\x00" * 1280 if self.active else b"idle"


class Speaker:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.beeps = 0

    async def open(self, rate: int) -> None: ...

    async def write(self, pcm: bytes) -> None:
        self.audio.append(pcm)

    async def close(self) -> None: ...

    async def beep(self) -> None:
        self.beeps += 1


class Wake:
    def process(self, frame: bytes) -> bool:
        return frame == b"WAKE"

    def reset(self) -> None: ...


class LiveServer:
    def __init__(self, tmp_path: Path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "devices.yaml").write_text(DEVICES, encoding="utf-8")
        (tmp_path / "config" / "satellites.yaml").write_text(
            yaml.safe_dump(
                {
                    "satellites": [
                        {
                            "id": "kueche-pi",
                            "room": "Küche",
                            "token_sha256": hash_token(TOKEN_KUECHE),
                        },
                        {"id": "flur-pi", "room": "Flur", "token_sha256": hash_token(TOKEN_FLUR)},
                    ]
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            password=PASSWORD,  # type: ignore[arg-type]
            session_secret="x" * 32,  # type: ignore[arg-type]
            static_dir=None,
            responder="echo",
            plugins="",
            data_dir=tmp_path,
            device_control="full",
            fastpath=True,
            summarize_sessions=False,
        )
        self.app = create_app(settings)
        self.state = self.app.state.cat
        self.backend = Backend()
        self.state.devices.register_backend("openhab", self.backend)
        self.state.devices.settle_delay = 0
        engine = make_engine(FakeStt("Mach das Licht an"), probs=[1.0] * 12)
        # Jede Sitzung bekommt eine frische Fake-VAD (die Wahrscheinlichkeitsliste läuft ab).
        engine._vad_factory = lambda: _fresh_vad()  # type: ignore[assignment]
        self.state.voice = engine
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "LiveServer":
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("Server startet nicht")

    def __exit__(self, *exc: Any) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/voice"


def _fresh_vad() -> Any:
    from tests.test_voice import FakeVad

    return FakeVad([1.0] * 12)


@pytest.fixture
def live(tmp_path: Path) -> Iterator[LiveServer]:
    with LiveServer(tmp_path) as server:
        yield server


def satellite(
    live: LiveServer, token: str, room: str = "egal", device: str = "pi"
) -> tuple[Satellite, FakeMic, Speaker]:
    config = parse_config(
        {
            "server_url": live.url,
            "token": token,
            "device_id": device,
            "room": room,
            "cooldown_s": 0.1,
            "server_timeout_s": 10,
        },
        env={},
    )
    mic, speaker = FakeMic(), Speaker()
    return Satellite(config, mic, speaker, Wake()), mic, speaker  # type: ignore[arg-type]


async def converse(sat: Satellite, mic: FakeMic, speaker: Speaker) -> asyncio.Task[Any]:
    task = asyncio.create_task(sat.session())
    for _ in range(300):  # auf das Wake-Word und den Streaming-Zustand warten
        if sat.mode is Mode.STREAM:
            break
        await asyncio.sleep(0.02)
    assert sat.mode is Mode.STREAM, "Wake-Word wurde nicht verarbeitet"
    mic.active = True
    for _ in range(400):
        if speaker.audio and sat.mode is Mode.WAKE:
            break
        await asyncio.sleep(0.02)
    return task


async def test_satellite_talks_to_real_server_and_room_comes_from_registration(
    live: LiveServer,
) -> None:
    # Der Satellit behauptet, im Flur zu sein: Der Server nimmt den Raum seines Tokens (Küche).
    sat, mic, speaker = satellite(live, TOKEN_KUECHE, room="Flur")
    task = await converse(sat, mic, speaker)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert speaker.beeps == 1 and speaker.audio, "keine Sprachausgabe angekommen"
    assert live.backend.sent == [("kuechenlicht", "on")]  # "Licht an" meint die Küche
    assert sat.mode is Mode.WAKE


async def test_second_satellite_uses_its_own_room(live: LiveServer) -> None:
    sat, mic, speaker = satellite(live, TOKEN_FLUR, room="Küche", device="flur-pi")
    task = await converse(sat, mic, speaker)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert live.backend.sent == [("flurlicht", "on")]


async def test_two_satellites_at_once_are_served_one_after_another(live: LiveServer) -> None:
    a, mic_a, speaker_a = satellite(live, TOKEN_KUECHE, device="kueche-pi")
    b, mic_b, speaker_b = satellite(live, TOKEN_FLUR, device="flur-pi")
    task_a, task_b = await asyncio.gather(
        converse(a, mic_a, speaker_a), converse(b, mic_b, speaker_b)
    )
    assert sorted(live.backend.sent) == [("flurlicht", "on"), ("kuechenlicht", "on")]
    assert speaker_a.audio and speaker_b.audio
    for task in (task_a, task_b):
        task.cancel()
    await asyncio.gather(task_a, task_b, return_exceptions=True)


async def test_connected_satellites_are_listed_via_registry(live: LiveServer) -> None:
    sat, mic, speaker = satellite(live, TOKEN_KUECHE, device="kueche-pi")
    task = asyncio.create_task(sat.session())
    for _ in range(200):
        if live.state.satellites.connected:
            break
        await asyncio.sleep(0.02)
    listing = {e["id"]: e["connected"] for e in live.state.satellites.listing()}
    assert listing == {"kueche-pi": True, "flur-pi": False}
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    for _ in range(200):
        if not live.state.satellites.connected:
            break
        await asyncio.sleep(0.02)
    assert live.state.satellites.connected == {}
    assert mic is not None and speaker is not None


async def test_wrong_token_is_rejected(live: LiveServer) -> None:
    sat, _, _ = satellite(live, "falsch" * 8)
    with pytest.raises(AuthRejected):
        await sat.session()
    assert live.backend.sent == []


async def test_no_token_means_no_access_even_with_browser_style_connection(
    live: LiveServer,
) -> None:
    import websockets

    with pytest.raises(websockets.exceptions.InvalidStatus):
        async with websockets.connect(live.url):
            pass


async def test_repeated_wrong_tokens_get_locked_out(live: LiveServer) -> None:
    for _ in range(10):
        sat, _, _ = satellite(live, "falsch" * 8)
        with pytest.raises(AuthRejected):
            await sat.session()
    good, mic, speaker = satellite(live, TOKEN_KUECHE, device="kueche-pi")
    with pytest.raises(AuthRejected):  # selbst das richtige Token ist kurz gesperrt
        await good.session()
    assert mic is not None and speaker is not None


# --- Register (Einheit) ---


def test_registry_loading_rules(tmp_path: Path) -> None:
    good = tmp_path / "ok.yaml"
    good.write_text(
        yaml.safe_dump(
            {"satellites": [{"id": "a", "room": "Küche", "token_sha256": hash_token("x" * 40)}]}
        ),
        encoding="utf-8",
    )
    reg = SatelliteRegistry.load(good)
    assert reg.error is None and reg.authenticate("x" * 40).id == "a"  # type: ignore[union-attr]
    assert reg.authenticate("y" * 40) is None
    assert SatelliteRegistry.load(tmp_path / "gibtsnicht.yaml").satellites == {}


@pytest.mark.parametrize(
    "content",
    [
        "satellites: 5",
        "satellites:\n  - {id: 'Gross', room: R, token_sha256: " + "a" * 64 + "}",
        "satellites:\n  - {id: a, room: '', token_sha256: " + "a" * 64 + "}",
        "satellites:\n  - {id: a, room: R, token_sha256: kurz}",
        "satellites:\n  - {id: a, room: R, token_sha256: "
        + "a" * 64
        + "}\n  - {id: a, room: R, token_sha256: "
        + "b" * 64
        + "}",
        "{kaputt: [",
    ],
)
def test_broken_registry_lets_nobody_in(tmp_path: Path, content: str) -> None:
    path = tmp_path / "s.yaml"
    path.write_text(content, encoding="utf-8")
    reg = SatelliteRegistry.load(path)
    assert reg.satellites == {} and reg.error
    assert reg.authenticate("irgendwas" * 5) is None


def test_plain_tokens_are_never_stored() -> None:
    assert hash_token("geheim") != "geheim" and len(hash_token("geheim")) == 64


def test_token_script_writes_a_registry_the_server_accepts(tmp_path: Path) -> None:
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "satellite_token.py"
    run = subprocess.run(
        [sys.executable, str(script), "wohnzimmer-pi", " Wohnzimmer ", "--data", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    token = run.stdout.strip().splitlines()[-2]
    text = (tmp_path / "config" / "satellites.yaml").read_text(encoding="utf-8")
    assert token not in text and "token_sha256" in text  # nur der Hash steht in der Datei
    registry = SatelliteRegistry.load(tmp_path / "config" / "satellites.yaml")
    found = registry.authenticate(token)
    assert found is not None and (found.id, found.room) == ("wohnzimmer-pi", "Wohnzimmer")
    # Ein zweiter Aufruf mit derselben ID ersetzt das Token (das alte ist ungültig).
    again = subprocess.run(
        [sys.executable, str(script), "wohnzimmer-pi", "Wohnzimmer", "--data", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    new_token = again.stdout.strip().splitlines()[-2]
    registry = SatelliteRegistry.load(tmp_path / "config" / "satellites.yaml")
    assert registry.authenticate(token) is None and registry.authenticate(new_token) is not None
    assert len(registry.satellites) == 1


def test_token_script_rejects_bad_ids(tmp_path: Path) -> None:
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts" / "satellite_token.py"
    run = subprocess.run(
        [sys.executable, str(script), "Böse ID", "Küche", "--data", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode != 0 and not (tmp_path / "config").exists()


def test_registry_picks_up_new_changed_and_removed_satellites_without_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "s.yaml"
    entry = {"id": "a", "room": "Küche", "token_sha256": hash_token("a" * 40)}
    path.write_text(yaml.safe_dump({"satellites": [entry]}), encoding="utf-8")
    reg = SatelliteRegistry.load(path)
    assert reg.authenticate("a" * 40) is not None
    assert reg.authenticate("b" * 40) is None  # noch unbekannt

    # neuer Satellit kommt dazu (anderer Dateiinhalt, also andere Größe/Zeit)
    second = {"id": "b", "room": "Flur", "token_sha256": hash_token("b" * 40)}
    path.write_text(yaml.safe_dump({"satellites": [entry, second]}), encoding="utf-8")
    assert reg.authenticate("b" * 40) is not None and len(reg.listing()) == 2

    # Sperren: Eintrag löschen gilt sofort
    path.write_text(yaml.safe_dump({"satellites": [second]}), encoding="utf-8")
    assert reg.authenticate("a" * 40) is None and reg.authenticate("b" * 40) is not None

    # kaputte Datei: niemand kommt herein, auch die Bisherigen nicht (fail closed)
    path.write_text("{kaputt: [", encoding="utf-8")
    assert reg.authenticate("b" * 40) is None and reg.error

    # Datei weg: keine Satelliten
    path.unlink()
    assert reg.authenticate("b" * 40) is None and reg.satellites == {}
