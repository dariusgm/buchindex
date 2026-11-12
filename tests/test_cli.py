import shutil

import pytest
from typer.testing import CliRunner

from buchindex import cli
from buchindex.state import STATUS_FEHLER, STATUS_OK, StateDB

from .conftest import make_text_pdf
from .fakes import FakeClient

runner = CliRunner()
ENV_VARS = ("BOOKS_DIR", "STATE_DB", "MEILI_URL", "MEILI_KEY", "MEILI_INDEX")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # keine fremde .env einlesen


@pytest.fixture
def programs(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda command: f"/bin/{command}")


def forbid_meili(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Meilisearch darf nicht verwendet werden")

    monkeypatch.setattr(cli.SearchIndex, "connect", fail)


def test_cli_aborts_when_program_is_missing(monkeypatch):
    monkeypatch.setattr(
        shutil, "which", lambda command: None if command == "pandoc" else f"/bin/{command}"
    )
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 1
    assert "pandoc" in result.output
    assert "apt install pandoc" in result.output


def test_missing_configuration(programs):
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert "BOOKS_DIR" in result.output


def test_dry_run_uses_neither_meili_nor_ocr(programs, monkeypatch, books_dir, tmp_path):
    make_text_pdf(books_dir / "neu.pdf", pages=1)
    monkeypatch.setenv("BOOKS_DIR", str(books_dir))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "state.db"))
    forbid_meili(monkeypatch)
    monkeypatch.setattr(cli.pipeline, "extract_file", forbid_meili)

    result = runner.invoke(cli.app, ["sync", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "neu: neu.pdf" in result.output
    assert "1 neu" in result.output
    with StateDB(tmp_path / "state.db") as state:
        assert state.files() == {}


def test_sync_reads_dotenv_and_indexes(programs, monkeypatch, books_dir, tmp_path):
    make_text_pdf(books_dir / "buch.pdf", pages=2)
    (tmp_path / ".env").write_text(
        f"BOOKS_DIR={books_dir}\nSTATE_DB={tmp_path / 'state.db'}\n"
        "MEILI_URL=http://meili.invalid:7700\nMEILI_KEY=geheim\n",
        encoding="utf-8",
    )
    client = FakeClient()
    monkeypatch.setattr(
        cli.SearchIndex,
        "connect",
        classmethod(lambda cls, url, key, name, settings, timeout=0: cls(client, name, settings)),
    )
    result = runner.invoke(cli.app, ["sync"])
    for name in ENV_VARS:  # load_dotenv schreibt in os.environ
        monkeypatch.delenv(name, raising=False)
    assert result.exit_code == 0, result.output
    assert "1 neu" in result.output
    assert len(client.indexes["buecher"]["documents"]) == 2


def test_status(programs, monkeypatch, tmp_path):
    with StateDB(tmp_path / "state.db") as state:
        state.record("a.pdf", "1", STATUS_OK)
        state.record("b.pdf", "2", STATUS_FEHLER, "ValueError: kaputt")
    monkeypatch.setenv("STATE_DB", str(tmp_path / "state.db"))
    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0
    assert "ok: 1" in result.output
    assert "fehler: 1" in result.output
    assert "b.pdf: ValueError: kaputt" in result.output


def test_check_reports_all_problems(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda command: None)
    forbid_meili(monkeypatch)
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 1
    assert "Fehlende Umgebungsvariablen" in result.output
    assert "tesseract" in result.output
    assert "qpdf" in result.output
    assert "Meilisearch: nicht geprüft" in result.output


def test_check_ok(programs, monkeypatch, books_dir, tmp_path):
    monkeypatch.setenv("BOOKS_DIR", str(books_dir))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("MEILI_URL", "http://meili.invalid:7700")
    monkeypatch.setenv("MEILI_KEY", "geheim")
    monkeypatch.setattr(
        cli.SearchIndex,
        "connect",
        classmethod(
            lambda cls, url, key, name, settings, timeout=0: cls(FakeClient(), name, settings)
        ),
    )
    result = runner.invoke(cli.app, ["check"])
    assert result.exit_code == 0, result.output
    assert "FEHLER" not in result.output
