"""ISBN-Erkennung per Regex mit Prüfziffernkontrolle."""

from __future__ import annotations

import re

_SEP = r"[-‐-– ]?"
_ISBN13 = re.compile(rf"(?<![\d-])97[89]{_SEP}(?:\d{_SEP}){{9}}\d(?![\d-])")
_ISBN10 = re.compile(rf"(?<![\d-])(?:\d{_SEP}){{9}}[\dXx](?![\d-])")


def _clean(candidate: str) -> str:
    return re.sub(r"[^0-9Xx]", "", candidate).upper()


def is_valid_isbn13(isbn: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", isbn):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(isbn))
    return total % 10 == 0


def is_valid_isbn10(isbn: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", isbn):
        return False
    total = sum((10 if c == "X" else int(c)) * (10 - i) for i, c in enumerate(isbn))
    return total % 11 == 0


def find_isbn(text: str) -> str | None:
    """Liefert die erste gültige ISBN-13, sonst die erste gültige ISBN-10."""
    for pattern, is_valid in ((_ISBN13, is_valid_isbn13), (_ISBN10, is_valid_isbn10)):
        for match in pattern.finditer(text):
            candidate = _clean(match.group())
            if is_valid(candidate):
                return candidate
    return None
