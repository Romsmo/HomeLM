import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cat.config import Settings
from cat.lan import is_private_host
from cat.main import create_app


@pytest.mark.parametrize(
    "host",
    [
        "192.168.0.20",
        "192.168.1.1",
        "192.168.1.78",
        "127.0.0.1",
        "::1",
        "172.19.0.1",
        "10.0.0.5",
        "::ffff:192.168.0.20",
        "fe80::1",
        "fd12:3456::1",
    ],
)
def test_private_hosts_are_local(host: str) -> None:
    assert is_private_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "217.88.249.83",
        "34.76.86.40",
        "8.8.8.8",
        "2a02:8071::1",
        "::ffff:8.8.8.8",
        "",
        None,
        "testclient",
    ],
)
def test_public_or_unknown_hosts_are_not_local(host: str | None) -> None:
    assert not is_private_host(host)


def _app(settings: Settings, lan_only: bool):
    return create_app(settings.model_copy(update={"lan_only": lan_only}))


def test_lan_client_gets_through(settings: Settings) -> None:
    with TestClient(_app(settings, True), client=("192.168.1.20", 5000)) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/api/me").status_code == 401  # normale Anmeldung, nicht gesperrt


def test_internet_client_is_rejected_everywhere(settings: Settings) -> None:
    with TestClient(_app(settings, True), client=("217.88.249.83", 5000)) as c:
        assert c.get("/health").status_code == 403
        assert c.post("/api/login", json={"password": "egal"}).status_code == 403
        assert c.get("/").status_code in (403, 404)
        with pytest.raises(WebSocketDisconnect) as err, c.websocket_connect("/ws"):
            pass
        assert err.value.code == 1008


def test_internet_client_passes_when_switched_off(settings: Settings) -> None:
    with TestClient(_app(settings, False), client=("217.88.249.83", 5000)) as c:
        assert c.get("/health").status_code == 200


def test_unknown_client_is_rejected_when_on(settings: Settings) -> None:
    # Fail closed: ohne erkennbare Adresse (z. B. "testclient") kommt nichts durch.
    with TestClient(_app(settings, True)) as c:
        assert c.get("/health").status_code == 403
