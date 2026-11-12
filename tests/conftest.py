from __future__ import annotations

import socket
from pathlib import Path

import pymupdf
import pytest

from buchindex.config import Settings

LOREM = "Dies ist ein Satz mit etwas Inhalt für die Suche. "


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Tests dürfen keine Netzwerkzugriffe machen (außer dem Integrationstest)."""
    if "integration" in request.keywords:
        return

    def blocked(*args, **kwargs):
        raise RuntimeError("Netzwerkzugriff im Test")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def make_text_pdf(path: Path, pages: int = 3, isbn: str | None = None) -> Path:
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 80), f"Kapitel {number}", fontsize=22)
        body = f"Inhalt von Seite {number}. " + LOREM * 8
        if isbn and number == 1:
            body = f"ISBN {isbn}. " + body
        page.insert_textbox(pymupdf.Rect(72, 120, 520, 700), body, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def make_empty_pdf(path: Path, pages: int = 2) -> Path:
    """PDF ohne Textebene, wie ein Scan."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(72, 72, 300, 300), fill=(0.8, 0.8, 0.8))
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def books_dir(tmp_path: Path) -> Path:
    path = tmp_path / "buecher"
    path.mkdir()
    return path


@pytest.fixture
def settings(tmp_path: Path, books_dir: Path) -> Settings:
    return Settings(
        books_dir=books_dir,
        state_db=tmp_path / "state" / "state.db",
        meili_url="http://meili.invalid:7700",
        meili_key="test-key",
    )
