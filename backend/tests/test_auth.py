from fastapi.testclient import TestClient

from cat.auth import LoginLimiter, SessionSigner
from cat.config import Settings
from cat.main import create_app
from tests.conftest import PASSWORD


def test_me_requires_login(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401


def test_login_wrong_password(client: TestClient) -> None:
    assert client.post("/api/login", json={"password": "falsch"}).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_login_sets_strict_httponly_cookie(client: TestClient) -> None:
    resp = client.post("/api/login", json={"password": PASSWORD})
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/me").status_code == 200


def test_logout_ends_session(authed: TestClient) -> None:
    authed.post("/api/logout")
    assert authed.get("/api/me").status_code == 401


def test_no_password_configured_means_no_login() -> None:
    settings = Settings(_env_file=None, static_dir=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/login", json={"password": ""}).status_code == 503
        assert c.get("/api/me").status_code == 401


def test_login_lockout_after_failures(client: TestClient) -> None:
    for _ in range(5):
        assert client.post("/api/login", json={"password": "x"}).status_code == 401
    resp = client.post("/api/login", json={"password": PASSWORD})
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


def test_forged_cookie_rejected(client: TestClient) -> None:
    client.cookies.set("cat_session", "e30=.deadbeef")
    assert client.get("/api/me").status_code == 401


def test_signer_expiry_and_tampering() -> None:
    now = [1000.0]
    signer = SessionSigner(b"k" * 32, ttl_s=10, clock=lambda: now[0])
    token = signer.issue()
    assert signer.verify(token)
    assert not signer.verify(token + "0")
    assert not signer.verify(None)
    now[0] += 11
    assert not signer.verify(token)


def test_limiter_unlocks_after_window() -> None:
    now = [0.0]
    limiter = LoginLimiter(max_failures=2, lockout_s=30, clock=lambda: now[0])
    limiter.record_failure("ip")
    limiter.record_failure("ip")
    assert limiter.retry_after("ip") > 0
    now[0] = 31
    assert limiter.retry_after("ip") == 0
