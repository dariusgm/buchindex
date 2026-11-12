"""Konfiguration ausschließlich über Umgebungsvariablen."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Fehlende oder ungültige Konfiguration."""


@dataclass(frozen=True)
class IndexSettings:
    """Index-Einstellungen für Meilisearch.

    `embedders` entspricht der Meilisearch-Einstellung `embedders`. Solange der
    Eintrag leer ist, wird er nicht an Meilisearch geschickt.
    """

    filterable: tuple[str, ...] = ("buch_id", "autor", "kategorie", "kapitel")
    sortable: tuple[str, ...] = ("pdf_seite",)
    searchable: tuple[str, ...] = ("text", "titel", "kapitel")
    embedders: Mapping[str, Any] = field(default_factory=dict)

    def to_meili(self) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "filterableAttributes": list(self.filterable),
            "sortableAttributes": list(self.sortable),
            "searchableAttributes": list(self.searchable),
        }
        if self.embedders:
            settings["embedders"] = dict(self.embedders)
        return settings


DOCUMENT_TEMPLATE = (
    "{% if doc.titel %}{{ doc.titel }}\n{% endif %}"
    "{% if doc.kapitel %}{{ doc.kapitel }}\n{% endif %}"
    "{{ doc.text }}"
)


def rest_embedder(
    url: str, model: str, dimensions: int | None, api_key: str | None, max_chunk_chars: int
) -> dict[str, Any]:
    """Meilisearch-Embedder für einen OpenAI-kompatiblen Endpunkt (`<url>/embeddings`).

    buchindex liefert die Vektoren der Passagen selbst mit. Meilisearch ruft den
    Endpunkt nur noch für Suchanfragen auf und muss ihn dafür erreichen können.
    """
    embedder: dict[str, Any] = {
        "source": "rest",
        "url": url.rstrip("/") + "/embeddings",
        "request": {"model": model, "input": ["{{text}}", "{{..}}"]},
        "response": {"data": [{"embedding": "{{embedding}}"}, "{{..}}"]},
        "documentTemplate": DOCUMENT_TEMPLATE,
        # Der Standard von 400 Bytes würde die Passagen abschneiden.
        "documentTemplateMaxBytes": 4 * max_chunk_chars + 1000,
    }
    if dimensions:
        embedder["dimensions"] = dimensions
    if api_key:
        embedder["apiKey"] = api_key
    return embedder


@dataclass(frozen=True)
class Settings:
    books_dir: Path | None
    state_db: Path | None
    meili_url: str | None
    meili_key: str | None
    meili_index: str = "buecher"
    ocr_lang: str = "deu"
    min_chars_per_page: int = 50
    max_chunk_chars: int = 1500
    meili_task_timeout: int = 3600
    work_dir: Path | None = None
    extract_jobs: int = 1
    embedder_name: str = "default"
    embedder_url: str | None = None
    embedder_model: str | None = None
    embedder_api_key: str | None = None
    embedder_dimensions: int | None = None
    embed_parallel: int = 1
    embed_batch_size: int = 8
    embed_timeout: int = 300
    index_settings: IndexSettings = field(default_factory=IndexSettings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def text(name: str) -> str | None:
            value = env.get(name, "").strip()
            return value or None

        def number(name: str, default: int | None) -> int | None:
            raw = text(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError:
                raise ConfigError(f"{name} muss eine ganze Zahl sein, ist aber {raw!r}.") from None
            if value <= 0:
                raise ConfigError(f"{name} muss größer als 0 sein, ist aber {value}.")
            return value

        max_chunk_chars = number("MAX_CHUNK_CHARS", 1500)
        embedder_name = text("EMBEDDER_NAME") or "default"
        embedder_url, embedder_model = text("EMBEDDER_URL"), text("EMBEDDER_MODEL")
        if bool(embedder_url) != bool(embedder_model):
            raise ConfigError("EMBEDDER_URL und EMBEDDER_MODEL müssen zusammen gesetzt sein.")
        embedder_dimensions = number("EMBEDDER_DIMENSIONS", None)
        embedder_api_key = text("EMBEDDER_API_KEY")
        embedders = {}
        if embedder_url:
            embedders[embedder_name] = rest_embedder(
                embedder_url, embedder_model, embedder_dimensions, embedder_api_key, max_chunk_chars
            )

        books_dir = text("BOOKS_DIR")
        state_db = text("STATE_DB")
        work_dir = text("WORK_DIR")
        return cls(
            books_dir=Path(books_dir) if books_dir else None,
            state_db=Path(state_db) if state_db else None,
            meili_url=text("MEILI_URL"),
            meili_key=text("MEILI_KEY"),
            meili_index=text("MEILI_INDEX") or "buecher",
            ocr_lang=text("OCR_LANG") or "deu",
            min_chars_per_page=number("MIN_CHARS_PER_PAGE", 50),
            max_chunk_chars=max_chunk_chars,
            meili_task_timeout=number("MEILI_TASK_TIMEOUT", 3600),
            work_dir=Path(work_dir) if work_dir else None,
            extract_jobs=number("EXTRACT_JOBS", 1),
            embedder_name=embedder_name,
            embedder_url=embedder_url,
            embedder_model=embedder_model,
            embedder_api_key=embedder_api_key,
            embedder_dimensions=embedder_dimensions,
            embed_parallel=number("EMBED_PARALLEL", 1),
            embed_batch_size=number("EMBED_BATCH_SIZE", 8),
            embed_timeout=number("EMBED_TIMEOUT", 300),
            index_settings=IndexSettings(embedders=embedders),
        )

    @property
    def work_path(self) -> Path:
        """Zwischenablage; ohne WORK_DIR ein Ordner neben der Datenbank."""
        if self.work_dir is not None:
            return self.work_dir
        return self.state_db.with_name(self.state_db.name + ".work")

    @property
    def embed_max_chars(self) -> int:
        """Obergrenze für den Text, der für eine Passage eingebettet wird."""
        return 4 * self.max_chunk_chars + 1000

    def missing(self, *names: str) -> list[str]:
        """Namen der Umgebungsvariablen aus `names`, die nicht gesetzt sind."""
        return [name for name in names if getattr(self, name.lower()) is None]

    def require(self, *names: str) -> None:
        missing = self.missing(*names)
        if missing:
            raise ConfigError("Fehlende Umgebungsvariablen: " + ", ".join(missing))
        if "BOOKS_DIR" in names and not self.books_dir.is_dir():
            raise ConfigError(f"BOOKS_DIR ist kein Verzeichnis: {self.books_dir}")
