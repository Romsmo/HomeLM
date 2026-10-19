from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cat.config import Settings
from cat.main import create_app

PASSWORD = "test-passwort"


@pytest.fixture(autouse=True)
def _no_people_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cat fragt im Chat nach dem Namen: das würde alle anderen Tests verfälschen. Die Tests
    für Personen schalten es mit Settings(people=True) ausdrücklich ein."""
    monkeypatch.setenv("CAT_PEOPLE", "false")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return client
