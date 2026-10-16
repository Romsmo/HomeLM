from pathlib import Path

from fastapi.testclient import TestClient

from cat import __version__
from cat.config import Settings
from cat.main import create_app


def test_health_ok() -> None:
    client = TestClient(create_app(Settings(static_dir=None)))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_serves_frontend_and_keeps_health(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Cat</h1>", encoding="utf-8")
    client = TestClient(create_app(Settings(static_dir=tmp_path)))
    assert client.get("/").text == "<h1>Cat</h1>"
    assert client.get("/health").json()["status"] == "ok"


def test_missing_static_dir_is_api_only(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(static_dir=tmp_path / "nope")))
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 404
