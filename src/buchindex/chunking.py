"""Markdown in Passagen aufteilen."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
KAPITEL_TRENNER = " > "


@dataclass(frozen=True)
class Passage:
    kapitel: str | None
    von_seite: int | None
    bis_seite: int | None
    text: str


@dataclass
class _Section:
    kapitel: str | None
    paragraphs: list[tuple[int | None, str]]


def book_id(pfad: str) -> str:
    """Stabile ID eines Buchs aus dem relativen Dateipfad."""
    return hashlib.sha256(pfad.encode("utf-8")).hexdigest()[:32]


def document_id(pfad: str, nummer: int) -> str:
    """Stabile Dokument-ID aus Pfad und laufender Nummer der Passage."""
    return hashlib.sha256(f"{pfad}\x00{nummer}".encode()).hexdigest()[:32]


def _heading_title(raw: str) -> str:
    """Überschrift ohne Markdown- und HTML-Auszeichnung."""
    title = re.sub(r"<[^>]+>", "", raw)
    title = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"[*_`]", "", title)
    return " ".join(title.split())


def _flush(buffer: list[str], section: _Section, page: int | None) -> None:
    text = "\n".join(buffer).strip()
    buffer.clear()
    if text:
        section.paragraphs.append((page, text))


def _split_sections(pages: Iterable[tuple[int | None, str]]) -> list[_Section]:
    sections = [_Section(None, [])]
    stack: list[tuple[int, str]] = []
    for page, markdown in pages:
        buffer: list[str] = []
        in_fence = False
        for line in markdown.splitlines():
            is_fence = bool(_FENCE.match(line))
            if is_fence or in_fence:
                # Codeblöcke bleiben zusammen, "#" darin ist keine Überschrift.
                in_fence = in_fence != is_fence
                buffer.append(line)
                continue
            heading = _HEADING.match(line)
            title = _heading_title(heading.group(2)) if heading else ""
            if title:
                _flush(buffer, sections[-1], page)
                level = len(heading.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                sections.append(_Section(KAPITEL_TRENNER.join(t for _, t in stack), []))
            elif not line.strip():
                _flush(buffer, sections[-1], page)
            else:
                buffer.append(line)
        _flush(buffer, sections[-1], page)
    return [s for s in sections if s.paragraphs]


def _split_long(text: str, max_chars: int) -> list[str]:
    """Teilt einen überlangen Absatz an Leerraum (Notlösung ohne Absatzgrenze)."""
    parts = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def chunk(pages: Iterable[tuple[int | None, str]], max_chars: int) -> list[Passage]:
    """Bildet Passagen aus (Seitenzahl, Markdown)-Paaren.

    Der Text wird an Überschriften in Abschnitte geteilt. Abschnitte über
    `max_chars` werden an Absatzgrenzen geteilt. `kapitel` ist der Pfad der
    Überschriften-Hierarchie, z. B. "Teil 1 > Kapitel 2".
    """
    passages: list[Passage] = []
    for section in _split_sections(pages):
        groups: list[list[tuple[int | None, str]]] = []
        length = 0
        for page, paragraph in section.paragraphs:
            for part in _split_long(paragraph, max_chars):
                if groups and length + 2 + len(part) <= max_chars:
                    groups[-1].append((page, part))
                    length += 2 + len(part)
                else:
                    groups.append([(page, part)])
                    length = len(part)
        for group in groups:
            passages.append(
                Passage(
                    kapitel=section.kapitel,
                    von_seite=group[0][0],
                    bis_seite=group[-1][0],
                    text="\n\n".join(text for _, text in group),
                )
            )
    return passages
