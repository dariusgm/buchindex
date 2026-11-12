"""Quellordner durchsuchen und mit dem gespeicherten Stand abgleichen."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from buchindex.state import STATUS_OK

SUFFIXES = {".pdf", ".epub"}


def fingerprint(path: Path) -> str:
    """Fingerprint aus Dateigröße und mtime."""
    stat = path.stat()
    return f"{stat.st_size}-{stat.st_mtime_ns}"


def scan(books_dir: Path) -> dict[str, str]:
    """Liefert relativer Pfad (POSIX-Schreibweise) -> Fingerprint."""
    found: dict[str, str] = {}
    for path in sorted(books_dir.rglob("*")):
        if path.suffix.lower() in SUFFIXES and path.is_file():
            found[path.relative_to(books_dir).as_posix()] = fingerprint(path)
    return found


@dataclass
class Diff:
    neu: list[str] = field(default_factory=list)
    geaendert: list[str] = field(default_factory=list)
    unveraendert: list[str] = field(default_factory=list)
    entfernt: list[str] = field(default_factory=list)


def diff(found: dict[str, str], known: dict[str, tuple[str, str]]) -> Diff:
    """Vergleicht gefundene Dateien mit `known` (pfad -> (fingerprint, status)).

    Dateien, die nicht vollständig verarbeitet wurden (Fehler oder Abbruch nach
    der Extraktion), gelten als geändert und werden dadurch erneut versucht.
    """
    result = Diff()
    for pfad, fp in found.items():
        if pfad not in known:
            result.neu.append(pfad)
        elif known[pfad][0] != fp or known[pfad][1] != STATUS_OK:
            result.geaendert.append(pfad)
        else:
            result.unveraendert.append(pfad)
    result.entfernt = sorted(set(known) - set(found))
    return result
