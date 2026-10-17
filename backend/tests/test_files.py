from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cat import api_files
from cat.config import Settings
from cat.files import FileError, Inbox, build_file_tools, clean_name, kind_of
from cat.main import create_app
from cat.state import AppState
from tests.conftest import PASSWORD


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        password=PASSWORD,  # type: ignore[arg-type]
        session_secret="x" * 32,  # type: ignore[arg-type]
        static_dir=None,
        responder="echo",
        plugins="",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as c:
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c


def state(client: TestClient) -> AppState:
    return client.app.state.cat  # type: ignore[no-any-return, attr-defined]


def test_clean_name_strips_paths_and_odd_characters() -> None:
    assert clean_name("../../etc/passwd") == "passwd"
    assert clean_name(r"C:\Users\x\Bericht 2026.pdf") == "Bericht 2026.pdf"
    assert clean_name("  ..hidden") == "hidden"
    assert clean_name("a<b>:c|d?.txt") == "a_b_c_d_.txt"
    assert clean_name("...") == "datei"
    assert clean_name("ä ö ü ß.md") == "ä ö ü ß.md"
    assert len(clean_name("x" * 300 + ".txt")) <= 100 and clean_name("x" * 300 + ".txt").endswith(
        ".txt"
    )


def test_kinds() -> None:
    assert [kind_of(n) for n in ("a.PNG", "b.md", "c.pdf", "d")] == [
        "image",
        "text",
        "other",
        "other",
    ]


def test_inbox_names_stay_unique_and_path_checks(tmp_path: Path) -> None:
    inbox = Inbox(tmp_path / "inbox")
    first = inbox.new_path("a.txt")
    first.write_text("1")
    second = inbox.new_path("a.txt")
    assert second.name == "a (2).txt"
    for bad in ("../x", ".versteckt", "sub/x.txt"):
        with pytest.raises(FileError):
            inbox.path_of(bad)
    with pytest.raises(FileError):
        inbox.path_of("fehlt.txt")


def test_upload_text_stores_file_announces_it_and_shows_on_stage(client: TestClient) -> None:
    r = client.put("/api/files/Notiz.md", content=b"# Titel\n\nHallo")
    assert r.status_code == 200
    assert r.json()["name"] == "Notiz.md" and r.json()["kind"] == "text"
    s = state(client)
    assert (s.settings.inbox_dir / "Notiz.md").read_text(encoding="utf-8") == "# Titel\n\nHallo"
    assert s.chat[-1].role == "system" and "Notiz.md" in s.chat[-1].text
    assert s.stage.items[-1].kind == "markdown" and "Hallo" in s.stage.items[-1].content
    audit = s.settings.audit_file.read_text(encoding="utf-8")
    assert "file_upload" in audit


def test_plain_text_is_fenced_on_stage(client: TestClient) -> None:
    client.put("/api/files/liste.csv", content=b"a,b\n1,2")
    assert state(client).stage.items[-1].content.startswith("```")


def test_image_goes_to_stage_by_name(client: TestClient) -> None:
    assert client.put("/api/files/Foto.png", content=b"\x89PNG\r\n\x1a\nxxxx").status_code == 200
    item = state(client).stage.items[-1]
    assert (item.kind, item.content, item.title) == ("image", "Foto.png", "Foto.png")


def test_other_files_are_stored_without_stage(client: TestClient) -> None:
    assert client.put("/api/files/Rechnung.pdf", content=b"%PDF-1.4").status_code == 200
    assert state(client).stage.items == []
    assert client.post("/api/files/Rechnung.pdf/show").status_code == 415


def test_hostile_names_are_cleaned(client: TestClient) -> None:
    r = client.put("/api/files/..%5C..%5Cevil.txt", content=b"x")
    assert r.status_code == 200 and r.json()["name"] == "evil.txt"
    assert not (state(client).settings.data_dir / "evil.txt").exists()


def test_empty_and_too_large_uploads_are_rejected(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert client.put("/api/files/leer.txt", content=b"").status_code == 400
    monkeypatch.setattr(api_files, "MAX_FILE_BYTES", 10)
    assert client.put("/api/files/gross.txt", content=b"x" * 11).status_code == 413
    leftovers = list(state(client).settings.inbox_dir.glob("*"))
    assert [p.name for p in leftovers] == [] or all(
        not p.name.startswith(".upload") for p in leftovers
    )


def test_streaming_limit_cleans_up_partial_files(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(api_files, "MAX_FILE_BYTES", 10)

    def chunks() -> Iterator[bytes]:  # ohne Content-Length (chunked)
        yield b"x" * 8
        yield b"y" * 8

    assert client.put("/api/files/stream.txt", content=chunks()).status_code == 413
    assert list(state(client).settings.inbox_dir.glob("*")) == []


def test_requires_login_and_same_origin(client: TestClient) -> None:
    other = TestClient(client.app)
    assert other.put("/api/files/x.txt", content=b"x").status_code == 401
    assert other.get("/api/files").status_code == 401
    r = client.put("/api/files/x.txt", content=b"x", headers={"origin": "https://boese.example"})
    assert r.status_code == 403


def test_download_headers_and_list_and_delete(client: TestClient) -> None:
    client.put("/api/files/a.txt", content=b"hallo")
    client.put("/api/files/b.png", content=b"\x89PNG")
    listing = client.get("/api/files").json()
    assert {f["name"] for f in listing} == {"a.txt", "b.png"}
    text = client.get("/api/files/a.txt")
    assert text.content == b"hallo"
    assert text.headers["content-disposition"].startswith("attachment")
    assert text.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in text.headers["content-security-policy"]
    assert client.get("/api/files/b.png").headers["content-disposition"].startswith("inline")
    assert client.get("/api/files/nein.txt").status_code == 404
    assert client.delete("/api/files/a.txt").json() == {"ok": True}
    assert client.get("/api/files/a.txt").status_code == 404
    assert client.delete("/api/files/a.txt").status_code == 404


def test_show_endpoint_puts_stored_file_on_stage(client: TestClient) -> None:
    client.put("/api/files/n.txt", content=b"Inhalt")
    state(client).stage.clear()
    assert client.post("/api/files/n.txt/show").status_code == 200
    assert state(client).stage.items[-1].title == "n.txt"


async def test_file_tools_list_and_read_text_only(tmp_path: Path) -> None:
    inbox = Inbox(tmp_path)
    (tmp_path / "a.txt").write_text("x" * 700, encoding="utf-8")
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    from cat.agent.tools import ToolContext, ToolError
    from cat.stage.store import StageStore

    async def emit(_: object) -> None: ...

    ctx = ToolContext(emit=emit, stage=StageStore())  # type: ignore[arg-type]
    tools = {t.name: t for t in build_file_tools(inbox)}
    listing = await tools["list_files"].handler({}, ctx)
    assert "a.txt | text" in listing and "b.pdf | other" in listing
    assert (await tools["read_file"].handler({"name": "a.txt", "max_chars": 300}, ctx)).endswith(
        "[gekürzt]"
    )
    with pytest.raises(ToolError, match="keine Textdatei"):
        await tools["read_file"].handler({"name": "b.pdf"}, ctx)
    with pytest.raises(ToolError):
        await tools["read_file"].handler({"name": "../x"}, ctx)
    assert (
        await build_file_tools(Inbox(tmp_path / "leer"))[0].handler({}, ctx)
        == "Es sind keine Dateien abgelegt."
    )
