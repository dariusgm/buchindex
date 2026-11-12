import shutil

import pytest

from buchindex import systemcheck


def test_all_programs_present(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda command: f"/bin/{command}")
    assert systemcheck.find_missing_programs() == []
    systemcheck.ensure_programs()


def test_missing_program_is_named_with_package(monkeypatch):
    monkeypatch.setattr(
        shutil, "which", lambda command: None if command == "tesseract" else f"/bin/{command}"
    )
    with pytest.raises(systemcheck.MissingProgramsError) as error:
        systemcheck.ensure_programs()
    message = str(error.value)
    assert "tesseract-ocr-deu" in message
    assert "tesseract-lang" in message
    assert "pandoc" not in message


def test_all_required_programs_are_checked(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda command: None)
    missing = {p.command for p in systemcheck.find_missing_programs()}
    assert missing == {"tesseract", "gs", "qpdf", "pandoc"}
