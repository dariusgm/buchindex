"""Der vollständige Verarbeitungsablauf in drei Stufen.

1. Extraktion: Text und Passagen jeder Datei, parallel mit `EXTRACT_JOBS` Prozessen.
2. Einbetten: Vektoren je Passage vom Embedding-Server (nur mit Embedder).
3. Schreiben: Passagen und Vektoren nach Meilisearch.

Die Ergebnisse von Stufe 1 und 2 liegen in der Zwischenablage, bis Stufe 3
für das Buch gelungen ist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from joblib import Parallel, delayed

from buchindex import epub, pdf
from buchindex.chunking import Passage, book_id, chunk, document_id
from buchindex.config import Settings
from buchindex.embedding import EmbeddingClient
from buchindex.isbn import find_isbn
from buchindex.metadata import Metadata, MetadataClient
from buchindex.scanner import Diff, diff, scan
from buchindex.search import SearchIndex
from buchindex.state import STATUS_EXTRAHIERT, STATUS_FEHLER, STATUS_OK, StateDB
from buchindex.workdir import WorkDir

log = logging.getLogger(__name__)

ISBN_PAGES = 5
# EPUBs haben keine Seiten; die ISBN wird am Anfang des Textes gesucht.
ISBN_EPUB_CHARS = 10_000


@dataclass
class Summary:
    neu: int = 0
    geaendert: int = 0
    uebersprungen: int = 0
    entfernt: int = 0
    fehler: int = 0


def plan(settings: Settings, state: StateDB) -> tuple[dict[str, str], Diff]:
    found = scan(settings.books_dir)
    return found, diff(found, state.files())


def path_category(pfad: str) -> list[str]:
    """Kategorie aus dem obersten Unterordner von BOOKS_DIR, falls vorhanden."""
    parts = PurePosixPath(pfad).parts
    return [parts[0]] if len(parts) > 1 else []


def build_documents(
    pfad: str, passages: list[Passage], isbn: str | None, meta: Metadata
) -> list[dict[str, Any]]:
    buch_id = book_id(pfad)
    kategorie = path_category(pfad) or list(meta.kategorie)
    return [
        {
            "id": document_id(pfad, nummer),
            "buch_id": buch_id,
            "datei": pfad,
            "titel": meta.titel,
            "autor": meta.autor,
            "isbn": isbn,
            "kategorie": kategorie,
            "kapitel": passage.kapitel,
            "von_seite": passage.von_seite,
            "bis_seite": passage.bis_seite,
            "pdf_seite": passage.von_seite,
            "gedruckte_seite": None,
            "text": passage.text,
        }
        for nummer, passage in enumerate(passages)
    ]


def embedding_text(document: dict[str, Any], max_chars: int) -> str:
    """Text, der für eine Passage eingebettet wird: Titel, Kapitel und Text."""
    parts = [document["titel"], document["kapitel"], document["text"]]
    return "\n".join(part for part in parts if part)[:max_chars]


# --- Stufe 1: Extraktion ---------------------------------------------------


def extract_file(pfad: str, fingerprint: str, settings: Settings) -> int:
    """Extrahiert die Passagen einer Datei in die Zwischenablage."""
    path = settings.books_dir / pfad
    pages: list[tuple[int | None, str]]
    if path.suffix.lower() == ".pdf":
        pages = list(pdf.extract_pages(path, settings.min_chars_per_page, settings.ocr_lang))
        head = "\n".join(text for _, text in pages[:ISBN_PAGES])
    else:
        markdown = epub.to_markdown(path)
        pages = [(None, markdown)]
        head = markdown[:ISBN_EPUB_CHARS]
    passages = chunk(pages, settings.max_chunk_chars)
    WorkDir(settings.work_path).save_extraction(pfad, fingerprint, find_isbn(head), passages)
    return len(passages)


def _extract_job(pfad: str, fingerprint: str, settings: Settings) -> tuple[str, int, str | None]:
    """Läuft in einem Arbeitsprozess; Fehler kommen als Text zurück."""
    try:
        return pfad, extract_file(pfad, fingerprint, settings), None
    except Exception as error:
        return pfad, 0, f"{type(error).__name__}: {error}"


def extract_all(
    pfade: list[str], found: dict[str, str], settings: Settings, state: StateDB
) -> dict[str, str]:
    """Extrahiert die Dateien mit `EXTRACT_JOBS` Prozessen. Liefert pfad -> Fehler."""
    work = WorkDir(settings.work_path)
    todo = [pfad for pfad in pfade if work.load_extraction(pfad, found[pfad]) is None]
    if len(todo) < len(pfade):
        log.info("%d Dateien sind bereits extrahiert", len(pfade) - len(todo))
    errors: dict[str, str] = {}
    results = Parallel(n_jobs=settings.extract_jobs, return_as="generator_unordered")(
        delayed(_extract_job)(pfad, found[pfad], settings) for pfad in todo
    )
    for nummer, (pfad, count, error) in enumerate(results, start=1):
        if error:
            log.error("Fehler beim Extrahieren von %s: %s", pfad, error)
            errors[pfad] = error
        else:
            log.info("Extrahiert (%d/%d): %s (%d Passagen)", nummer, len(todo), pfad, count)
            state.record(pfad, found[pfad], STATUS_EXTRAHIERT)
    return errors


# --- Stufe 2 und 3: Einbetten und Schreiben ----------------------------------


def embed_documents(
    pfad: str,
    fingerprint: str,
    documents: list[dict[str, Any]],
    settings: Settings,
    embedder: EmbeddingClient,
) -> None:
    """Hängt jedem Dokument seinen Vektor an; fertige Vektoren kommen aus der Zwischenablage."""
    work = WorkDir(settings.work_path)
    vectors = work.load_vectors(pfad, fingerprint, embedder.model, len(documents))
    if vectors is None:
        texts = [embedding_text(document, settings.embed_max_chars) for document in documents]
        vectors = embedder.embed(texts)
        work.save_vectors(pfad, fingerprint, embedder.model, vectors)
    for document, vector in zip(documents, vectors, strict=True):
        # `regenerate: False` hält Meilisearch davon ab, selbst einzubetten.
        document["_vectors"] = {settings.embedder_name: {"embeddings": vector, "regenerate": False}}


def index_file(
    pfad: str,
    fingerprint: str,
    settings: Settings,
    index: SearchIndex,
    metadata: MetadataClient,
    embedder: EmbeddingClient | None,
) -> int:
    """Bettet die extrahierten Passagen ein und schreibt sie nach Meilisearch."""
    extraction = WorkDir(settings.work_path).load_extraction(pfad, fingerprint)
    if extraction is None:
        raise RuntimeError("Extraktion fehlt in der Zwischenablage")
    meta = metadata.lookup(extraction.isbn) if extraction.isbn else Metadata()
    documents = build_documents(pfad, extraction.passages, extraction.isbn, meta)
    if embedder is not None:
        embed_documents(pfad, fingerprint, documents, settings, embedder)
    index.replace_book(book_id(pfad), documents)
    return len(documents)


def sync(
    settings: Settings,
    state: StateDB,
    index: SearchIndex,
    metadata: MetadataClient,
    embedder: EmbeddingClient | None = None,
) -> Summary:
    found, changes = plan(settings, state)
    summary = Summary(uebersprungen=len(changes.unveraendert))
    index.ensure_index()
    work = WorkDir(settings.work_path)
    kinds = dict.fromkeys(changes.neu, "neu") | dict.fromkeys(changes.geaendert, "geaendert")

    errors = extract_all(list(kinds), found, settings, state)
    for pfad, error in errors.items():
        state.record(pfad, found[pfad], STATUS_FEHLER, error)
        summary.fehler += 1

    pending = [pfad for pfad in kinds if pfad not in errors]
    for nummer, pfad in enumerate(pending, start=1):
        try:
            count = index_file(pfad, found[pfad], settings, index, metadata, embedder)
        except Exception as error:  # eine fehlerhafte Datei bricht den Lauf nicht ab
            log.exception("Fehler bei %s", pfad)
            state.record(pfad, found[pfad], STATUS_FEHLER, f"{type(error).__name__}: {error}")
            summary.fehler += 1
        else:
            log.info("Indexiert (%d/%d): %s (%d Passagen)", nummer, len(pending), pfad, count)
            state.record(pfad, found[pfad], STATUS_OK)
            work.discard(pfad)
            setattr(summary, kinds[pfad], getattr(summary, kinds[pfad]) + 1)

    for pfad in changes.entfernt:
        try:
            index.delete_book(book_id(pfad))
        except Exception:
            log.exception("Fehler beim Entfernen von %s", pfad)
            summary.fehler += 1
        else:
            log.info("Entfernt: %s", pfad)
            state.remove(pfad)
            work.discard(pfad)
            summary.entfernt += 1

    log.info(
        "Zusammenfassung: neu=%d, geändert=%d, übersprungen=%d, entfernt=%d, Fehler=%d",
        summary.neu,
        summary.geaendert,
        summary.uebersprungen,
        summary.entfernt,
        summary.fehler,
    )
    return summary
