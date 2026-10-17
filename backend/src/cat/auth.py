"""Passwort-Login mit signiertem Sitzungs-Cookie (ohne externe Abhängigkeiten)."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from cat.config import Settings

COOKIE_NAME = "cat_session"


class SessionSigner:
    def __init__(self, secret: bytes, ttl_s: float, clock: Callable[[], float] = time.time) -> None:
        self._secret = secret
        self.ttl_s = ttl_s
        self._clock = clock

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def issue(self) -> str:
        body = json.dumps({"exp": self._clock() + self.ttl_s, "n": secrets.token_hex(8)}).encode()
        return f"{base64.urlsafe_b64encode(body).decode()}.{self._sign(body)}"

    def verify(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        raw, _, sig = token.partition(".")
        try:
            body = base64.urlsafe_b64decode(raw.encode())
            exp = float(json.loads(body)["exp"])
        except (ValueError, KeyError, TypeError):
            return False
        if not hmac.compare_digest(sig, self._sign(body)):
            return False
        return exp > self._clock()


class LoginLimiter:
    """Sperrt eine Quelle nach zu vielen Fehlversuchen kurz (im Speicher)."""

    def __init__(
        self,
        max_failures: int = 5,
        lockout_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._lockout = lockout_s
        self._clock = clock
        self._failures: dict[str, tuple[int, float]] = {}

    def retry_after(self, key: str) -> float:
        count, since = self._failures.get(key, (0, 0.0))
        if count < self._max:
            return 0.0
        remaining = since + self._lockout - self._clock()
        if remaining <= 0:
            self._failures.pop(key, None)
            return 0.0
        return remaining

    def record_failure(self, key: str) -> None:
        count, _ = self._failures.get(key, (0, 0.0))
        self._failures[key] = (count + 1, self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


class Auth:
    def __init__(self, settings: Settings) -> None:
        self._password = settings.password.get_secret_value() if settings.password else None
        secret = (
            settings.session_secret.get_secret_value().encode()
            if settings.session_secret
            else secrets.token_bytes(32)
        )
        self.signer = SessionSigner(secret, settings.session_ttl_hours * 3600)
        self.limiter = LoginLimiter()

    @property
    def configured(self) -> bool:
        return bool(self._password)

    def check_password(self, candidate: str) -> bool:
        if not self._password:
            return False
        return hmac.compare_digest(
            hashlib.sha256(candidate.encode()).digest(),
            hashlib.sha256(self._password.encode()).digest(),
        )

    def is_authenticated(self, cookies: dict[str, str]) -> bool:
        return self.signer.verify(cookies.get(COOKIE_NAME))


class LoginBody(BaseModel):
    password: str


def _auth(request: Request) -> Auth:
    return request.app.state.auth


def require_auth(request: Request) -> None:
    if not _auth(request).is_authenticated(request.cookies):
        raise HTTPException(status_code=401, detail="Nicht angemeldet")


Authed = Annotated[None, Depends(require_auth)]

router = APIRouter(prefix="/api")


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response) -> dict[str, bool]:
    auth = _auth(request)
    if not auth.configured:
        raise HTTPException(503, "Kein Passwort konfiguriert (CAT_PASSWORD in der .env setzen)")
    key = request.client.host if request.client else "unknown"
    wait = auth.limiter.retry_after(key)
    if wait > 0:
        raise HTTPException(429, "Zu viele Versuche", headers={"Retry-After": str(int(wait) + 1)})
    if not auth.check_password(body.password):
        auth.limiter.record_failure(key)
        raise HTTPException(401, "Falsches Passwort")
    auth.limiter.reset(key)
    response.set_cookie(
        COOKIE_NAME,
        auth.signer.issue(),
        max_age=int(auth.signer.ttl_s),
        httponly=True,
        # Über HTTPS nur verschlüsselt senden (über HTTP im LAN geht es nicht anders).
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(_: Authed) -> dict[str, bool]:
    return {"authenticated": True}
