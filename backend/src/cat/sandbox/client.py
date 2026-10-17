"""Client für die Code-Sandbox: legt Aufträge im gemeinsamen Ordner ab und liest Ergebnisse.

Die Sandbox ist ein eigener Container ohne Netzwerk (sandbox/worker.py). Cat und Sandbox
tauschen nur Dateien in `data/sandbox` aus; Cat braucht dafür keinen Docker-Zugriff.
"""

import asyncio
import base64
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

MAX_CODE = 20_000
MAX_TIMEOUT = 30
CLAIM_WAIT_S = 4.0
HEARTBEAT_MAX_AGE_S = 15.0
POLL_S = 0.15
MAX_IMAGE_TOTAL = 1_500_000


class SandboxError(Exception):
    """Sandbox nicht nutzbar oder Auftrag abgelehnt; Meldung darf angezeigt werden."""


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    error: str | None = None
    images: list[bytes] = field(default_factory=list)


class SandboxClient:
    def __init__(self, base: Path) -> None:
        self._base = base

    def is_alive(self, now: float | None = None) -> bool:
        beat = self._base / "heartbeat"
        try:
            return (now or time.time()) - beat.stat().st_mtime < HEARTBEAT_MAX_AGE_S
        except OSError:
            return False

    async def run(self, code: str, limit_s: int = 10) -> SandboxResult:
        if not code.strip():
            raise SandboxError("Der Code ist leer.")
        if len(code) > MAX_CODE:
            raise SandboxError(f"Der Code ist zu lang (erlaubt {MAX_CODE} Zeichen).")
        limit_s = max(1, min(int(limit_s), MAX_TIMEOUT))
        if not self.is_alive():
            raise SandboxError(
                "Die Code-Sandbox läuft nicht (Container homelm-sandbox). "
                "Python-Code wird nur dort ausgeführt, nie im Cat-Prozess."
            )
        job = self._base / "jobs" / uuid.uuid4().hex
        try:
            return await self._run_job(job, code, limit_s)
        finally:
            await asyncio.to_thread(shutil.rmtree, job, ignore_errors=True)

    async def _run_job(self, job: Path, code: str, limit_s: int) -> SandboxResult:
        await asyncio.to_thread(self._write_job, job, code, limit_s)
        started = time.monotonic()
        deadline = started + limit_s + 10
        while time.monotonic() < deadline:
            result = job / "result.json"
            if result.exists():
                return await asyncio.to_thread(self._read_result, job)
            if not (job / "claimed").exists() and time.monotonic() - started > CLAIM_WAIT_S:
                raise SandboxError("Die Code-Sandbox hat den Auftrag nicht angenommen.")
            await asyncio.sleep(POLL_S)
        raise SandboxError("Die Code-Sandbox hat nicht rechtzeitig geantwortet.")

    @staticmethod
    def _write_job(job: Path, code: str, timeout: int) -> None:
        job.mkdir(parents=True)
        (job / "code.py").write_text(code, encoding="utf-8")
        tmp = job / "request.json.tmp"
        tmp.write_text(json.dumps({"timeout": timeout}), encoding="utf-8")
        tmp.replace(job / "request.json")  # erst jetzt sieht der Worker den Auftrag

    @staticmethod
    def _read_result(job: Path) -> SandboxResult:
        raw = json.loads((job / "result.json").read_text(encoding="utf-8"))
        images: list[bytes] = []
        total = 0
        for name in raw.get("images", [])[:5]:
            path = job / "work" / str(name)
            if path.is_symlink() or not path.is_file() or "/" in str(name) or "\\" in str(name):
                continue
            data = path.read_bytes()
            total += len(data)
            if total <= MAX_IMAGE_TOTAL and data.startswith(b"\x89PNG"):
                images.append(data)
        return SandboxResult(
            ok=bool(raw.get("ok")),
            stdout=str(raw.get("stdout", "")),
            stderr=str(raw.get("stderr", "")),
            exit_code=raw.get("exit_code"),
            timed_out=bool(raw.get("timed_out")),
            duration_ms=int(raw.get("duration_ms", 0)),
            error=raw.get("error"),
            images=images,
        )


def image_html(images: list[bytes], title: str) -> str:
    """Stage-HTML mit eingebetteten PNGs (data:-URLs sind in der Stage-CSP erlaubt)."""
    tags = "".join(
        f'<img alt="{title} {i + 1}" src="data:image/png;base64,{base64.b64encode(img).decode()}">'
        for i, img in enumerate(images)
    )
    style = (
        "body{margin:0;padding:12px;display:flex;flex-wrap:wrap;gap:12px;"
        "align-items:flex-start;justify-content:center;background:#fff}"
        "img{max-width:100%;height:auto;background:#fff;border-radius:6px}"
    )
    return f"<style>{style}</style>{tags}"
