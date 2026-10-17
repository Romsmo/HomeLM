"""Sandbox-Worker: führt Python-Aufträge aus einem gemeinsamen Ordner aus.

Läuft in einem Container ohne Netzwerk (network_mode: none), mit schreibgeschütztem
Dateisystem, ohne Capabilities und mit Speicher-, CPU- und Prozesslimit. Cat legt Aufträge als
Ordner <jobs>/jobs/<id>/ ab (code.py, dann request.json) und liest das Ergebnis aus result.json.

Dieses Skript hat bewusst keine Abhängigkeiten außer der Standardbibliothek.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

JOB_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TEXT = 20_000
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 1_500_000
MAX_TIMEOUT = 30
POLL_S = 0.3
HEARTBEAT_S = 2.0
JOB_MAX_AGE_S = 600


def _limits(timeout: int):  # type: ignore[no-untyped-def]
    """Ressourcenlimits für den Kindprozess (nur POSIX)."""
    import resource

    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 1, timeout + 1))
        resource.setrlimit(resource.RLIMIT_AS, (450 * 1024 * 1024, 450 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()

    return apply


def _clip(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if len(text) > MAX_TEXT:
        return text[:MAX_TEXT] + f"\n… ({len(text)} Zeichen, gekürzt)"
    return text


def collect_images(work: Path) -> list[str]:
    """PNG-Dateien (keine Symlinks, begrenzte Größe) aus dem Arbeitsordner."""
    images = []
    for path in sorted(work.glob("*.png")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.stat().st_size > MAX_IMAGE_BYTES:
            continue
        images.append(path.name)
        if len(images) >= MAX_IMAGES:
            break
    return images


def run_job(job: Path) -> dict[str, object]:
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    timeout = max(1, min(int(request.get("timeout", 10)), MAX_TIMEOUT))
    work = job / "work"
    work.mkdir(exist_ok=True)
    started = time.monotonic()
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": "/tmp/mpl",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
    }
    timed_out = False
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(job / "code.py")],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_limits(timeout),  # noqa: PLW1509 - nötig für setrlimit/setsid
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        exit_code = proc.returncode
        # Nach jedem Auftrag die ganze Prozessgruppe beenden: nichts darf übrig bleiben.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except OSError as exc:
        return {"ok": False, "error": f"Start fehlgeschlagen: {exc.strerror}", "images": []}
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": _clip(out),
        "stderr": _clip(err),
        "images": collect_images(work),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def process_pending(base: Path) -> int:
    done = 0
    jobs = base / "jobs"
    if not jobs.is_dir():
        return 0
    for job in sorted(jobs.iterdir()):
        if not JOB_ID.match(job.name) or job.is_symlink() or not job.is_dir():
            continue
        if (job / "result.json").exists() or not (job / "request.json").exists():
            continue
        (job / "claimed").write_text("1", encoding="utf-8")  # Cat sieht: ein Worker lebt
        try:
            result = run_job(job)
        except Exception as exc:  # der Worker darf an keinem Auftrag sterben
            result = {"ok": False, "error": f"Interner Fehler: {type(exc).__name__}", "images": []}
        tmp = job / "result.json.tmp"
        tmp.write_text(json.dumps(result), encoding="utf-8")
        tmp.replace(job / "result.json")
        done += 1
    return done


def cleanup(base: Path, now: float | None = None) -> None:
    now = now or time.time()
    jobs = base / "jobs"
    if not jobs.is_dir():
        return
    for job in jobs.iterdir():
        if JOB_ID.match(job.name) and job.is_dir() and not job.is_symlink():
            if now - job.stat().st_mtime > JOB_MAX_AGE_S:
                shutil.rmtree(job, ignore_errors=True)


def main(base: Path) -> None:
    (base / "jobs").mkdir(parents=True, exist_ok=True)
    last_beat = 0.0
    last_clean = 0.0
    while True:
        now = time.time()
        if now - last_beat >= HEARTBEAT_S:
            (base / "heartbeat").write_text(str(now), encoding="utf-8")
            last_beat = now
        if now - last_clean >= 60:
            cleanup(base)
            last_clean = now
        if not process_pending(base):
            time.sleep(POLL_S)


if __name__ == "__main__":
    main(Path(os.environ.get("SANDBOX_DIR", "/jobs")))
