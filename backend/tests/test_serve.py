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


def test_proxy_headers_are_trusted_only_for_configured_proxies() -> None:
    configs = build_configs(settings(), FastAPI())
    assert configs[0].proxy_headers is False  # ohne Proxy: nie X-Forwarded-* glauben
    trusted = build_configs(settings(trusted_proxies="172.19.0.0/16, 10.0.0.5"), FastAPI())
    assert trusted[0].proxy_headers is True
    assert trusted[0].forwarded_allow_ips == "172.19.0.0/16, 10.0.0.5"


async def test_behind_the_proxy_the_real_client_ip_and_scheme_count() -> None:
    """Anmelde-Sperre je echter Client-IP statt gemeinsam für alle hinter Caddy; Cookie Secure."""
    import httpx

    from cat.main import create_app
    from tests.conftest import PASSWORD

    app = create_app(
        settings(password=PASSWORD, session_secret="x" * 32, static_dir=None, responder="echo")
    )
    config = build_configs(settings(trusted_proxies="172.19.0.0/16"), app)[0]
    config.load()  # baut die App mit der Proxy-Schicht, wie uvicorn beim Start
    caddy = httpx.ASGITransport(app=config.loaded_app, client=("172.19.0.2", 4000))
    stranger = httpx.ASGITransport(app=config.loaded_app, client=("203.0.113.9", 4000))

    def headers(ip: str) -> dict[str, str]:
        return {"x-forwarded-for": ip, "x-forwarded-proto": "https"}

    async with httpx.AsyncClient(transport=caddy, base_url="http://cat") as c:
        # 10 Fehlversuche von Angreifer 1 sperren nur Angreifer 1
        for _ in range(11):
            await c.post("/api/login", json={"password": "falsch"}, headers=headers("93.184.216.1"))
        blocked = await c.post(
            "/api/login", json={"password": PASSWORD}, headers=headers("93.184.216.1")
        )
        assert blocked.status_code == 429
        ok = await c.post(
            "/api/login", json={"password": PASSWORD}, headers=headers("93.184.216.2")
        )
        assert ok.status_code == 200
        assert "secure" in ok.headers["set-cookie"].lower().split("; ")  # Schema https vom Proxy

    # Ein Fremder, der nicht Caddy ist, kann die Client-IP nicht fälschen: sein Header zählt nicht.
    async with httpx.AsyncClient(transport=stranger, base_url="http://cat") as c:
        spoof = await c.post(
            "/api/login", json={"password": PASSWORD}, headers=headers("93.184.216.99")
        )
        assert spoof.status_code == 200
        assert "secure" not in spoof.headers["set-cookie"].lower().split("; ")


async def test_distributed_guessing_from_the_internet_locks_everyone_out_but_not_the_lan() -> None:
    import httpx

    from cat.main import create_app
    from tests.conftest import PASSWORD

    app = create_app(
        settings(password=PASSWORD, session_secret="x" * 32, static_dir=None, responder="echo")
    )
    config = build_configs(settings(trusted_proxies="172.19.0.0/16"), app)[0]
    config.load()
    caddy = httpx.ASGITransport(app=config.loaded_app, client=("172.19.0.2", 4000))
    async with httpx.AsyncClient(transport=caddy, base_url="http://cat") as c:
        # 20 Fehlversuche aus 20 verschiedenen Internet-Adressen (je nur einer) ...
        for i in range(20):
            await c.post(
                "/api/login",
                json={"password": "falsch"},
                headers={"x-forwarded-for": f"93.184.216.{i + 1}"},
            )
        # ... sperren die Anmeldung von außen, auch mit dem richtigen Passwort.
        late = await c.post(
            "/api/login",
            json={"password": PASSWORD},
            headers={"x-forwarded-for": "93.184.216.200"},
        )
        assert late.status_code == 429
        # Aus dem Heimnetz geht es weiter.
        home = await c.post(
            "/api/login", json={"password": PASSWORD}, headers={"x-forwarded-for": "192.168.0.50"}
        )
        assert home.status_code == 200
