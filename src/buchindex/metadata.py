"""Metadaten über die Open Library API, mit Cache in SQLite."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from buchindex.state import StateDB

log = logging.getLogger(__name__)

OPEN_LIBRARY_URL = "https://openlibrary.org"


@dataclass(frozen=True)
class Metadata:
    titel: str | None = None
    autor: str | None = None
    kategorie: tuple[str, ...] = ()


def _unique(values: list[str]) -> tuple[str, ...]:
    """Entfernt Dubletten ohne Rücksicht auf Groß- und Kleinschreibung."""
    seen: dict[str, str] = {}
    for value in values:
        if isinstance(value, str) and value.strip():
            seen.setdefault(value.strip().casefold(), value.strip())
    return tuple(seen.values())


class MetadataClient:
    def __init__(self, state: StateDB, http: httpx.Client | None = None):
        self._state = state
        self._http = http or httpx.Client(
            follow_redirects=True, timeout=20.0, headers={"User-Agent": "buchindex"}
        )

    def lookup(self, isbn: str) -> Metadata:
        """Fragt Titel und Autor ab. Unbekannte ISBNs liefern leere Metadaten.

        Netzwerk- und Serverfehler werden nicht gecacht, sondern als
        `httpx.HTTPError` weitergereicht.
        """
        hit, cached = self._state.cached_isbn(isbn)
        if hit:
            if not cached:
                return Metadata()
            return Metadata(
                titel=cached.get("titel"),
                autor=cached.get("autor"),
                kategorie=tuple(cached.get("kategorie", ())),
            )

        response = self._http.get(f"{OPEN_LIBRARY_URL}/isbn/{isbn}.json")
        if response.status_code == 404:
            log.info("ISBN %s ist bei Open Library unbekannt", isbn)
            self._state.cache_isbn(isbn, None)
            return Metadata()
        response.raise_for_status()
        book = response.json()

        # Autoren und Themen stehen oft nur am Werk, nicht an der Ausgabe.
        work = {}
        works = book.get("works") or []
        if works and works[0].get("key"):
            work = self._get_json(f"{works[0]['key']}.json")

        author_keys = [a.get("key") for a in book.get("authors") or []]
        if not any(author_keys):
            author_keys = [(a.get("author") or {}).get("key") for a in work.get("authors") or []]
        names = [self._get_json(f"{key}.json").get("name") for key in author_keys if key]

        metadata = Metadata(
            titel=book.get("title") or work.get("title") or None,
            autor=", ".join(_unique(names)) or None,
            kategorie=_unique([*(book.get("subjects") or []), *(work.get("subjects") or [])]),
        )
        self._state.cache_isbn(
            isbn,
            {
                "titel": metadata.titel,
                "autor": metadata.autor,
                "kategorie": list(metadata.kategorie),
            },
        )
        return metadata

    def _get_json(self, path: str) -> dict:
        response = self._http.get(f"{OPEN_LIBRARY_URL}{path}")
        response.raise_for_status()
        return response.json()
