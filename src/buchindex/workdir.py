"""Zwischenablage für die Ergebnisse der einzelnen Verarbeitungsstufen.

Pro Buch liegen hier bis zum erfolgreichen Schreiben nach Meilisearch die
extrahierten Passagen und, falls ein Embedder konfiguriert ist, die Vektoren.
Schlägt eine spätere Stufe fehl, muss die frühere nicht wiederholt werden.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from buchindex.chunking import Passage, book_id


@dataclass(frozen=True)
class Extraction:
    isbn: str | None
    passages: list[Passage]


class WorkDir:
    def __init__(self, path: Path):
        self._path = path

    def _file(self, pfad: str, stage: str) -> Path:
        return self._path / f"{book_id(pfad)}.{stage}.json"

    def _write(self, target: Path, data: dict[str, Any]) -> None:
        self._path.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)  # halbe Dateien bleiben nie unter dem Zielnamen liegen

    def _read(self, pfad: str, stage: str, fingerprint: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._file(pfad, stage).read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        return data if data.get("fingerprint") == fingerprint else None

    def save_extraction(
        self, pfad: str, fingerprint: str, isbn: str | None, passages: list[Passage]
    ) -> None:
        self._write(
            self._file(pfad, "passagen"),
            {
                "pfad": pfad,
                "fingerprint": fingerprint,
                "isbn": isbn,
                "passagen": [asdict(passage) for passage in passages],
            },
        )

    def load_extraction(self, pfad: str, fingerprint: str) -> Extraction | None:
        """Liefert die gespeicherte Extraktion, wenn sie zum Fingerprint passt."""
        data = self._read(pfad, "passagen", fingerprint)
        if data is None:
            return None
        return Extraction(data["isbn"], [Passage(**passage) for passage in data["passagen"]])

    def save_vectors(
        self, pfad: str, fingerprint: str, model: str, vectors: list[list[float]]
    ) -> None:
        self._write(
            self._file(pfad, "vektoren"),
            {"pfad": pfad, "fingerprint": fingerprint, "modell": model, "vektoren": vectors},
        )

    def load_vectors(
        self, pfad: str, fingerprint: str, model: str, count: int
    ) -> list[list[float]] | None:
        """Liefert gespeicherte Vektoren, wenn sie zu Datei, Modell und Passagenzahl passen."""
        data = self._read(pfad, "vektoren", fingerprint)
        if data is None or data.get("modell") != model or len(data["vektoren"]) != count:
            return None
        return data["vektoren"]

    def discard(self, pfad: str) -> None:
        for stage in ("passagen", "vektoren"):
            self._file(pfad, stage).unlink(missing_ok=True)
