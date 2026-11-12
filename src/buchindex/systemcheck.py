"""Prüfung, ob die benötigten Systemprogramme im PATH liegen."""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Program:
    command: str
    apt: str
    brew: str


REQUIRED_PROGRAMS: tuple[Program, ...] = (
    Program("tesseract", "tesseract-ocr tesseract-ocr-deu", "tesseract tesseract-lang"),
    Program("gs", "ghostscript", "ghostscript"),
    Program("qpdf", "qpdf", "qpdf"),
    Program("pandoc", "pandoc", "pandoc"),
)


class MissingProgramsError(Exception):
    def __init__(self, missing: list[Program]):
        self.missing = missing
        lines = ["Benötigte Systemprogramme fehlen im PATH:"]
        lines += [
            f"  - {p.command}: installieren mit `apt install {p.apt}` bzw. `brew install {p.brew}`"
            for p in missing
        ]
        super().__init__("\n".join(lines))


def find_missing_programs() -> list[Program]:
    return [p for p in REQUIRED_PROGRAMS if shutil.which(p.command) is None]


def ensure_programs() -> None:
    missing = find_missing_programs()
    if missing:
        raise MissingProgramsError(missing)
