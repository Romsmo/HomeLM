import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from cat.agent.tools import ToolContext, ToolError
from cat.config import Settings
from cat.devices.service import DeviceService
from cat.plugins.external import load_external
from cat.plugins.pending import MAX_PENDING, PendingPlugins, build_pending_tools
from cat.plugins.registry import PluginServices, build_plugins
from cat.sandbox.client import SandboxClient, SandboxError, image_html
from cat.sandbox.tools import build_sandbox_tools
from cat.stage.store import StageStore
from cat.ws.protocol import ServerEvent, StageShow

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FakeWorker:
    """Spielt das Protokoll des echten Workers nach (sandbox/worker.py)."""

    def __init__(
        self, base: Path, result: dict[str, Any] | None = None, claim: bool = True
    ) -> None:
        self.base = base
        self.result = result or {"ok": True, "exit_code": 0, "stdout": "42\n", "stderr": ""}
        self.claim = claim
        self.seen: list[dict[str, Any]] = []
        self._stop = False
        (base / "jobs").mkdir(parents=True, exist_ok=True)
        self.beat()

    def beat(self) -> None:
        (self.base / "heartbeat").write_text(str(time.time()), encoding="utf-8")

    async def run(self) -> None:
        while not self._stop:
            for job in sorted((self.base / "jobs").glob("*")):
                req = job / "request.json"
                if not req.exists() or (job / "result.json").exists():
                    continue
                if self.claim:
                    (job / "claimed").write_text("1")
                self.seen.append(
                    {"code": (job / "code.py").read_text(), "request": json.loads(req.read_text())}
                )
                work = job / "work"
                work.mkdir(exist_ok=True)
                for name in self.result.get("images", []):
                    (work / name).write_bytes(PNG)
                if self.claim:
                    (job / "result.json").write_text(json.dumps(self.result))
            await asyncio.sleep(0.02)

    def stop(self) -> None:
        self._stop = True


@pytest.fixture
async def worker(tmp_path: Path):
    w = FakeWorker(tmp_path)
    task = asyncio.create_task(w.run())
    yield w
    w.stop()
    await task


async def test_client_runs_job_and_cleans_up(tmp_path: Path, worker: FakeWorker) -> None:
    result = await SandboxClient(tmp_path).run("print(6*7)", 5)
    assert result.ok and result.stdout == "42\n"
    assert worker.seen == [{"code": "print(6*7)", "request": {"timeout": 5}}]
    assert list((tmp_path / "jobs").iterdir()) == []  # Auftragsordner aufgeräumt


async def test_timeout_is_capped(tmp_path: Path, worker: FakeWorker) -> None:
    await SandboxClient(tmp_path).run("x=1", 9999)
    assert worker.seen[0]["request"]["timeout"] == 30


async def test_images_are_returned_only_if_real_png(tmp_path: Path) -> None:
    w = FakeWorker(tmp_path, {"ok": True, "stdout": "", "images": ["a.png", "../boese.png"]})
    task = asyncio.create_task(w.run())
    try:
        result = await SandboxClient(tmp_path).run("plot", 5)
    finally:
        w.stop()
        await task
    assert result.images == [PNG]  # "../boese.png" wird verworfen


async def test_rejects_empty_oversized_code(tmp_path: Path, worker: FakeWorker) -> None:
    client = SandboxClient(tmp_path)
    with pytest.raises(SandboxError, match="leer"):
        await client.run("  ")
    with pytest.raises(SandboxError, match="zu lang"):
        await client.run("x" * 20_001)
    assert worker.seen == []


async def test_dead_sandbox_is_reported_not_run_locally(tmp_path: Path) -> None:
    client = SandboxClient(tmp_path)  # kein Heartbeat
    assert not client.is_alive()
    with pytest.raises(SandboxError, match="Container homelm-sandbox"):
        await client.run("print(1)")
    (tmp_path / "heartbeat").write_text("x")
    old = time.time() - 60
    os.utime(tmp_path / "heartbeat", (old, old))
    assert not client.is_alive()


async def test_unclaimed_job_gives_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cat.sandbox.client.CLAIM_WAIT_S", 0.2)
    w = FakeWorker(tmp_path, claim=False)
    task = asyncio.create_task(w.run())
    try:
        with pytest.raises(SandboxError, match="nicht angenommen"):
            await SandboxClient(tmp_path).run("print(1)")
    finally:
        w.stop()
        await task


def test_image_html_embeds_data_urls_allowed_by_the_stage_csp() -> None:
    html = image_html([PNG], "Titel")
    assert f"data:image/png;base64,{base64.b64encode(PNG).decode()}" in html
    assert "http" not in html  # nichts Externes, passt zur CSP (img-src data:)


# --- Werkzeug ---


class Sink:
    def __init__(self) -> None:
        self.events: list[ServerEvent] = []

    async def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


def tool_for(tmp_path: Path) -> tuple[Any, ToolContext, Sink]:
    sink = Sink()
    tool = build_sandbox_tools(SandboxClient(tmp_path))[0]
    return tool, ToolContext(emit=sink, stage=StageStore()), sink


async def test_tool_returns_output_and_shows_images_on_stage(tmp_path: Path) -> None:
    w = FakeWorker(
        tmp_path, {"ok": True, "stdout": "Summe: 10\n", "stderr": "", "images": ["bild.png"]}
    )
    task = asyncio.create_task(w.run())
    tool, ctx, sink = tool_for(tmp_path)
    try:
        out = await tool.handler({"code": "print(10)"}, ctx)
    finally:
        w.stop()
        await task
    assert "Summe: 10" in out and "1 Bild" in out
    shown = [e for e in sink.events if isinstance(e, StageShow)]
    assert shown and shown[0].item.kind == "html" and "data:image/png" in shown[0].item.content


@pytest.mark.parametrize(
    ("result", "fragment"),
    [
        ({"ok": False, "timed_out": True, "stdout": "", "stderr": ""}, "Zeitlimit"),
        ({"ok": False, "exit_code": 1, "stdout": "", "stderr": "NameError: x"}, "NameError"),
        ({"ok": False, "error": "Start fehlgeschlagen"}, "Start fehlgeschlagen"),
    ],
)
async def test_tool_reports_failures_to_the_model(
    tmp_path: Path, result: dict, fragment: str
) -> None:
    w = FakeWorker(tmp_path, result)
    task = asyncio.create_task(w.run())
    tool, ctx, _ = tool_for(tmp_path)
    try:
        with pytest.raises(ToolError, match=fragment):
            await tool.handler({"code": "x"}, ctx)
    finally:
        w.stop()
        await task


async def test_tool_without_sandbox_explains_itself(tmp_path: Path) -> None:
    tool, ctx, _ = tool_for(tmp_path)
    with pytest.raises(ToolError, match="Sandbox"):
        await tool.handler({"code": "print(1)"}, ctx)
    with pytest.raises(ToolError, match="code"):
        await tool.handler({}, ctx)


# --- Der echte Worker (nur POSIX; in Docker auf dem Server zusätzlich geprüft) ---


@pytest.mark.skipif(sys.platform == "win32", reason="Worker nutzt POSIX-Ressourcenlimits")
def test_real_worker_runs_code_with_limits(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
    import worker

    job = tmp_path / "jobs" / ("a" * 32)
    job.mkdir(parents=True)
    (job / "code.py").write_text("print('hallo')\nopen('x.png','wb').write(b'\\x89PNG')\n")
    (job / "request.json").write_text('{"timeout": 5}')
    assert worker.process_pending(tmp_path) == 1
    result = json.loads((job / "result.json").read_text())
    assert result["ok"] and result["stdout"] == "hallo\n" and result["images"] == ["x.png"]

    loop = tmp_path / "jobs" / ("b" * 32)
    loop.mkdir()
    (loop / "code.py").write_text("while True: pass\n")
    (loop / "request.json").write_text('{"timeout": 1}')
    worker.process_pending(tmp_path)
    assert json.loads((loop / "result.json").read_text())["timed_out"] is True


def test_worker_ignores_odd_job_names_and_symlinks(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sandbox"))
    import worker

    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    odd = tmp_path / "jobs" / "nicht-hex"
    odd.mkdir()
    (odd / "request.json").write_text("{}")
    assert worker.process_pending(tmp_path) == 0
    work = tmp_path / "w"
    work.mkdir()
    (work / "echt.png").write_bytes(b"\x89PNG")
    (work / "gross.png").write_bytes(b"x" * (worker.MAX_IMAGE_BYTES + 1))
    assert worker.collect_images(work) == ["echt.png"]


# --- Plugin-Vorschläge: nie automatisch aktiv ---

EVIL = "import os\nopen(os.environ.get('PWN', 'pwned.txt'), 'w').write('boese')\nPLUGIN = None\n"


def test_proposal_is_written_but_never_executed(tmp_path: Path) -> None:
    pending = PendingPlugins(tmp_path / "plugins")
    folder = pending.propose("Müll Kalender!", "Zeigt Termine.", EVIL)
    assert folder.parent == tmp_path / "plugins" / "pending" and folder.name == "muell_kalender"
    assert (folder / "plugin.py").read_text().startswith("import os")
    assert "NICHT AKTIV" in (folder / "README.md").read_text(encoding="utf-8")
    assert json.loads((folder / "meta.json").read_text())["state"] == "pending"
    assert not Path("pwned.txt").exists() and not (folder / "pwned.txt").exists()
    assert pending.list() == ["muell_kalender"]


def test_proposals_never_overwrite_and_are_bounded(tmp_path: Path) -> None:
    pending = PendingPlugins(tmp_path)
    a = pending.propose("x", "d", "PLUGIN = 1")
    b = pending.propose("x", "d", "PLUGIN = 2")
    assert a != b and (a / "plugin.py").read_text() == "PLUGIN = 1\n"
    with pytest.raises(ToolError):
        pending.propose("y", "d", "  ")
    with pytest.raises(ToolError, match="zu lang"):
        pending.propose("y", "d", "x" * 30_001)
    for i in range(MAX_PENDING):
        try:
            pending.propose(f"p{i}", "d", "PLUGIN = 0")
        except ToolError:
            break
    with pytest.raises(ToolError, match="zu viele"):
        pending.propose("zuviel", "d", "PLUGIN = 0")


def test_path_tricks_in_names_stay_inside_pending(tmp_path: Path) -> None:
    folder = PendingPlugins(tmp_path / "p").propose("../../etc/cron", "d", "PLUGIN = 1")
    assert folder.resolve().is_relative_to((tmp_path / "p" / "pending").resolve())


async def test_propose_tool_shows_code_and_says_it_is_inactive(tmp_path: Path) -> None:
    sink = Sink()
    tool = build_pending_tools(PendingPlugins(tmp_path))[0]
    out = await tool.handler(
        {"name": "wetter2", "description": "Mehr Wetter", "code": "PLUGIN = 1"},
        ToolContext(emit=sink, stage=StageStore()),
    )
    assert "NICHT aktiv" in out and "von Hand" in out
    shown = [e for e in sink.events if isinstance(e, StageShow)]
    assert (
        shown and "Nicht aktiv" in shown[0].item.content and "PLUGIN = 1" in shown[0].item.content
    )


# --- Laden: nur freigegebene, nur wenn in CAT_PLUGINS ---

GOOD = """
class P:
    name = "meins"
    async def start(self, ctx): pass
    async def stop(self): pass
    def tools(self): return []
    def widgets(self): return []
    def intents(self): return []
    async def refresh(self, widget_id): return False

PLUGIN = P()
"""


def services(tmp_path: Path) -> PluginServices:
    async def emit(_: ServerEvent) -> None: ...

    from cat.audit import AuditLog
    from cat.devices.allowlist import Allowlist
    from cat.devices.confirm import ConfirmManager

    return PluginServices(
        devices=DeviceService(
            Allowlist(), "readonly", emit, AuditLog(None), ConfirmManager(emit, lambda: False)
        )
    )


def settings(tmp_path: Path, plugins: str) -> Settings:
    return Settings(_env_file=None, static_dir=None, plugins=plugins, data_dir=tmp_path)  # type: ignore[call-arg]


def test_pending_plugin_is_inactive_even_if_listed(tmp_path: Path) -> None:
    PendingPlugins(tmp_path / "plugins").propose("meins", "d", GOOD)
    built = build_plugins(settings(tmp_path, "meins"), services(tmp_path))
    assert built == []  # liegt nur in pending/: wird nie geladen


def test_approved_plugin_loads_only_when_listed(tmp_path: Path) -> None:
    active = tmp_path / "plugins" / "active" / "meins"
    active.mkdir(parents=True)
    (active / "plugin.py").write_text(GOOD, encoding="utf-8")
    assert (
        build_plugins(settings(tmp_path, ""), services(tmp_path)) == []
    )  # freigegeben, aber nicht aktiviert
    built = build_plugins(settings(tmp_path, "meins"), services(tmp_path))
    assert [p.name for p in built] == ["meins"]


def test_broken_or_unfit_external_plugins_are_skipped(tmp_path: Path) -> None:
    active = tmp_path / "active"
    for name, code in {
        "kaputt": "raise RuntimeError('x')",
        "leer": "PLUGIN = object()",
        "syntax": "def (",
    }.items():
        (active / name).mkdir(parents=True)
        (active / name / "plugin.py").write_text(code, encoding="utf-8")
    for name in ("kaputt", "leer", "syntax", "gibtsnicht", "../x", "A B"):
        assert load_external(active, name, None) is None


def test_builtin_names_cannot_be_shadowed_by_active_plugins(tmp_path: Path) -> None:
    shadow = tmp_path / "plugins" / "active" / "system"
    shadow.mkdir(parents=True)
    (shadow / "plugin.py").write_text(GOOD.replace('"meins"', '"falsch"'), encoding="utf-8")
    built = build_plugins(settings(tmp_path, "system"), services(tmp_path))
    assert [p.name for p in built] == ["system"]
