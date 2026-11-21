from pathlib import Path

from fastapi.testclient import TestClient

from cat.config import Settings
from cat.main import create_app

PASSWORD = "test-passwort"


def _client(settings: Settings, certs: Path | None, ca: bool = True) -> TestClient:
    update: dict[str, object] = {}
    if certs is not None:
        (certs / "server.crt").write_text("CERT")
        (certs / "server.key").write_text("KEY")
        if ca:
            (certs / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nCA\n")
        update = {"tls_cert": certs / "server.crt", "tls_key": certs / "server.key"}
    c = TestClient(create_app(settings.model_copy(update=update)))
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return c


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/tls").status_code == 401
    assert client.get("/api/ca.crt").status_code == 401


def test_without_tls(settings: Settings) -> None:
    with _client(settings, None) as c:
        assert c.get("/api/tls").json() == {"https": False, "port": 8490, "ca": False}
        assert c.get("/api/ca.crt").status_code == 404


def test_with_tls_serves_only_the_public_ca(settings: Settings, tmp_path: Path) -> None:
    with _client(settings, tmp_path) as c:
        assert c.get("/api/tls").json() == {"https": True, "port": 8490, "ca": True}
        r = c.get("/api/ca.crt")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/x-x509-ca-cert"
        assert "cat-heimnetz-ca.crt" in r.headers["content-disposition"]
        assert r.text.startswith("-----BEGIN CERTIFICATE-----")
        assert "KEY" not in r.text


def test_tls_without_ca_file(settings: Settings, tmp_path: Path) -> None:
    with _client(settings, tmp_path, ca=False) as c:
        assert c.get("/api/tls").json()["ca"] is False
        assert c.get("/api/ca.crt").status_code == 404
