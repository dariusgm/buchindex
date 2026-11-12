"""Verarbeitungsstand und ISBN-Cache in SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_OK = "ok"
STATUS_FEHLER = "fehler"
# Passagen liegen in der Zwischenablage, sind aber noch nicht im Index.
STATUS_EXTRAHIERT = "extrahiert"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    pfad TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    verarbeitet_am TEXT NOT NULL,
    status TEXT NOT NULL,
    fehler TEXT
);
CREATE TABLE IF NOT EXISTS isbn_cache (
    isbn TEXT PRIMARY KEY,
    antwort TEXT NOT NULL,
    abgefragt_am TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StateDB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StateDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- files ---------------------------------------------------------

    def files(self) -> dict[str, tuple[str, str]]:
        """Liefert pfad -> (fingerprint, status)."""
        rows = self._conn.execute("SELECT pfad, fingerprint, status FROM files")
        return {pfad: (fingerprint, status) for pfad, fingerprint, status in rows}

    def record(self, pfad: str, fingerprint: str, status: str, fehler: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO files (pfad, fingerprint, verarbeitet_am, status, fehler) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(pfad) DO UPDATE SET fingerprint = excluded.fingerprint, "
                "verarbeitet_am = excluded.verarbeitet_am, status = excluded.status, "
                "fehler = excluded.fehler",
                (pfad, fingerprint, _now(), status, fehler),
            )

    def remove(self, pfad: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM files WHERE pfad = ?", (pfad,))

    def status_counts(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status")
        return dict(rows.fetchall())

    def last_errors(self, limit: int = 10) -> list[tuple[str, str, str]]:
        """Liefert (pfad, verarbeitet_am, fehler) der letzten Fehler."""
        rows = self._conn.execute(
            "SELECT pfad, verarbeitet_am, fehler FROM files WHERE status = ? "
            "ORDER BY verarbeitet_am DESC, pfad LIMIT ?",
            (STATUS_FEHLER, limit),
        )
        return rows.fetchall()

    # --- ISBN-Cache ----------------------------------------------------

    def cached_isbn(self, isbn: str) -> tuple[bool, dict[str, Any] | None]:
        """Liefert (Treffer im Cache, gecachte Antwort)."""
        row = self._conn.execute(
            "SELECT antwort FROM isbn_cache WHERE isbn = ?", (isbn,)
        ).fetchone()
        if row is None:
            return False, None
        return True, json.loads(row[0])

    def cache_isbn(self, isbn: str, antwort: dict[str, Any] | None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO isbn_cache (isbn, antwort, abgefragt_am) VALUES (?, ?, ?)",
                (isbn, json.dumps(antwort), _now()),
            )
