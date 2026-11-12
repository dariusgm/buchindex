"""PDF-Verarbeitung: Textprüfung, OCR-Kopie, seitenweises Markdown."""

from __future__ import annotations

import contextlib
import io
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf
import pymupdf4llm

log = logging.getLogger(__name__)


def chars_per_page(path: Path) -> float:
    """Durchschnittliche Zahl der Textzeichen pro Seite."""
    with pymupdf.open(path) as doc:
        if doc.page_count == 0:
            return 0.0
        total = sum(len(page.get_text().strip()) for page in doc)
        return total / doc.page_count


def needs_ocr(path: Path, min_chars_per_page: int) -> bool:
    """Eine PDF gilt als textbasiert, wenn sie im Schnitt die Schwelle erreicht."""
    return chars_per_page(path) < min_chars_per_page


def ocr_copy(source: Path, target: Path, lang: str) -> None:
    """Erzeugt mit ocrmypdf eine OCR-Kopie. Die Quelldatei bleibt unverändert."""
    result = subprocess.run(
        [sys.executable, "-m", "ocrmypdf", "--skip-text", "-l", lang, str(source), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ocrmypdf ist fehlgeschlagen: {result.stderr.strip()[-500:]}")


_PICTURE_TEXT = re.compile(
    r"<!-- Start of picture text -->(.*?)<!-- End of picture text -->", re.DOTALL
)


def clean_markdown(text: str) -> str:
    """Entfernt die Markierungen, die pymupdf4llm um Text in Abbildungen und Formeln setzt."""
    return _PICTURE_TEXT.sub(lambda m: m.group(1).replace("<br>", " ").strip(), text)


def to_markdown_pages(path: Path) -> list[tuple[int, str]]:
    """Liefert (PDF-Seitenzahl ab 1, Markdown) für jede Seite."""
    messages = io.StringIO()
    with contextlib.redirect_stdout(messages):
        chunks = pymupdf4llm.to_markdown(
            str(path),
            page_chunks=True,
            show_progress=False,
            use_ocr=False,  # OCR läuft ausschließlich über ocrmypdf
            header=False,  # Kolumnentitel und Seitenzahlen stören die Suche
            footer=False,
        )
    if messages.getvalue().strip():
        log.debug("pymupdf4llm: %s", messages.getvalue().strip())
    return [(number, clean_markdown(chunk["text"])) for number, chunk in enumerate(chunks, start=1)]


def extract_pages(path: Path, min_chars_per_page: int, ocr_lang: str) -> list[tuple[int, str]]:
    """Extrahiert seitenweises Markdown, bei Scans über eine temporäre OCR-Kopie."""
    if not needs_ocr(path, min_chars_per_page):
        return to_markdown_pages(path)
    log.info("Kein Text gefunden, starte OCR: %s", path.name)
    with tempfile.TemporaryDirectory(prefix="buchindex-ocr-") as tmp:
        target = Path(tmp) / "ocr.pdf"
        ocr_copy(path, target, ocr_lang)
        return to_markdown_pages(target)
