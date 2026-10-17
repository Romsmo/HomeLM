from pathlib import Path

from fastapi import FastAPI

from cat.config import Settings
from cat.serve import build_configs, tls_ready


def settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, plugins="", **kwargs)  # type: ignore[call-arg]


def test_http_only_without_certificates() -> None:
    configs = build_configs(settings(), FastAPI())
    assert [c.port for c in configs] == [8000] and configs[0].ssl_certfile is None


def test_https_is_added_when_certificate_and_key_exist(tmp_path: Path) -> None:
    cert, key = tmp_path / "server.crt", tmp_path / "server.key"
    cert.write_text("x")
    key.write_text("y")
    configs = build_configs(settings(tls_cert=cert, tls_key=key, tls_port=8443), FastAPI())
    assert [c.port for c in configs] == [8000, 8443]
    https = configs[1]
    assert https.ssl_certfile == str(cert) and https.ssl_keyfile == str(key)
    assert https.lifespan == "off"  # Plugins und Sprache starten nur einmal (HTTP-Server)
    assert configs[0].lifespan == "auto"


def test_missing_files_fall_back_to_http_with_a_warning(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    s = settings(tls_cert=tmp_path / "nope.crt", tls_key=tmp_path / "nope.key")
    assert tls_ready(s) is False
    assert len(build_configs(s, FastAPI())) == 1
    assert "Zertifikat oder Schlüssel fehlen" in caplog.text


def test_only_one_of_the_two_files_is_not_enough(tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    cert.write_text("x")
    assert tls_ready(settings(tls_cert=cert)) is False
