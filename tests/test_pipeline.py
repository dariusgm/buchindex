from dataclasses import replace

import httpx
import pytest

from buchindex import pdf, pipeline
from buchindex.chunking import book_id
from buchindex.config import IndexSettings
from buchindex.embedding import EmbeddingClient
from buchindex.metadata import MetadataClient
from buchindex.search import SearchIndex
from buchindex.state import STATUS_EXTRAHIERT, STATUS_FEHLER, STATUS_OK, StateDB

from .conftest import make_empty_pdf, make_text_pdf
from .fakes import FakeClient

ISBN = "9783161484100"


def open_library(request):
    if request.url.path == f"/isbn/{ISBN}.json":
        return httpx.Response(
            200,
            json={"title": "Ein Buch", "authors": [{"key": "/authors/A"}], "subjects": ["Thema"]},
        )
    if request.url.path == "/authors/A.json":
        return httpx.Response(200, json={"name": "Ada Autorin"})
    return httpx.Response(404)


@pytest.fixture
def env(settings, monkeypatch):
    """Ablauf mit gemocktem Meilisearch-Client, gemockter HTTP-Schicht und OCR."""
    ocr_calls = []

    def fake_ocr(source, target, lang):
        ocr_calls.append(source.name)
        make_text_pdf(target, pages=2)

    monkeypatch.setattr(pdf, "ocr_copy", fake_ocr)
    client = FakeClient()
    state = StateDB(settings.state_db)
    http = httpx.Client(transport=httpx.MockTransport(open_library))

    class Env:
        pass

    env = Env()
    env.settings = settings
    env.client = client
    env.state = state
    env.ocr_calls = ocr_calls
    env.run = lambda embedder=None, settings=settings: pipeline.sync(
        settings,
        state,
        SearchIndex(client, settings.meili_index, IndexSettings()),
        MetadataClient(state, http),
        embedder,
    )
    env.work_files = lambda: sorted(p.name for p in settings.work_path.glob("*"))
    env.documents = lambda: client.indexes[settings.meili_index]["documents"]
    yield env
    state.close()


def test_end_to_end(env):
    books = env.settings.books_dir
    (books / "unter").mkdir()
    make_text_pdf(books / "text.pdf", pages=3, isbn="978-3-16-148410-0")
    make_empty_pdf(books / "unter" / "scan.pdf", pages=2)

    summary = env.run()
    assert (summary.neu, summary.geaendert, summary.uebersprungen, summary.fehler) == (2, 0, 0, 0)
    assert env.ocr_calls == ["scan.pdf"]

    documents = list(env.documents().values())
    text_docs = sorted(
        (d for d in documents if d["datei"] == "text.pdf"), key=lambda d: d["von_seite"]
    )
    assert [(d["kapitel"], d["von_seite"], d["bis_seite"]) for d in text_docs] == [
        ("Kapitel 1", 1, 1),
        ("Kapitel 2", 2, 2),
        ("Kapitel 3", 3, 3),
    ]
    for d in text_docs:
        assert f"Inhalt von Seite {d['von_seite']}." in d["text"]
        assert (d["titel"], d["autor"], d["isbn"]) == ("Ein Buch", "Ada Autorin", ISBN)
        assert d["buch_id"] == book_id("text.pdf")
        assert d["pdf_seite"] == d["von_seite"]
        assert d["gedruckte_seite"] is None

    scan_docs = [d for d in documents if d["datei"] == "unter/scan.pdf"]
    assert sorted(d["von_seite"] for d in scan_docs) == [1, 2]
    assert all((d["titel"], d["autor"], d["isbn"]) == (None, None, None) for d in scan_docs)
    # Kategorie: Unterordner hat Vorrang, sonst die Themen von Open Library.
    assert all(d["kategorie"] == ["unter"] for d in scan_docs)
    assert all(d["kategorie"] == ["Thema"] for d in text_docs)

    # Zweiter Lauf: nichts wird neu verarbeitet.
    calls = list(env.client.calls)
    ids = set(env.documents())
    summary = env.run()
    assert (summary.neu, summary.geaendert, summary.uebersprungen) == (0, 0, 2)
    assert env.client.calls == calls
    assert env.ocr_calls == ["scan.pdf"]
    assert set(env.documents()) == ids


def test_changed_file_is_reindexed_without_duplicates(env):
    path = env.settings.books_dir / "text.pdf"
    make_text_pdf(path, pages=3)
    env.run()
    assert len(env.documents()) == 3

    make_text_pdf(path, pages=1)
    summary = env.run()
    assert summary.geaendert == 1
    assert len(env.documents()) == 1


def test_removed_file_is_deleted_from_index_and_state(env):
    path = env.settings.books_dir / "text.pdf"
    make_text_pdf(path)
    make_text_pdf(env.settings.books_dir / "bleibt.pdf", pages=1)
    env.run()

    path.unlink()
    summary = env.run()
    assert summary.entfernt == 1
    assert {d["datei"] for d in env.documents().values()} == {"bleibt.pdf"}
    assert set(env.state.files()) == {"bleibt.pdf"}


def test_broken_file_does_not_abort_and_is_retried(env):
    books = env.settings.books_dir
    (books / "kaputt.pdf").write_bytes(b"das ist keine PDF")
    make_text_pdf(books / "text.pdf", pages=1)

    summary = env.run()
    assert (summary.neu, summary.fehler) == (1, 1)
    files = env.state.files()
    assert files["kaputt.pdf"][1] == STATUS_FEHLER
    assert files["text.pdf"][1] == STATUS_OK
    assert env.state.last_errors()[0][0] == "kaputt.pdf"

    # Nächster Lauf versucht die fehlerhafte Datei erneut.
    summary = env.run()
    assert (summary.uebersprungen, summary.fehler) == (1, 1)


def test_books_dir_is_never_written(env):
    books = env.settings.books_dir
    make_text_pdf(books / "text.pdf", pages=1)
    make_empty_pdf(books / "scan.pdf")
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in books.rglob("*")}
    env.run()
    assert {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in books.rglob("*")} == before


class FakeEmbedder(EmbeddingClient):
    model = "modell"

    def __init__(self, fail=False):
        self.fail = fail
        self.texts = []

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("Embedding-Server nicht erreichbar")
        self.texts.extend(texts)
        return [[float(len(text)), 0.0] for text in texts]


def count_extractions(monkeypatch):
    calls = []
    original = pipeline.extract_file

    def counting(pfad, fingerprint, settings):
        calls.append(pfad)
        return original(pfad, fingerprint, settings)

    monkeypatch.setattr(pipeline, "extract_file", counting)
    return calls


def test_vectors_are_attached_and_work_dir_is_cleaned(env):
    make_text_pdf(env.settings.books_dir / "text.pdf", pages=2, isbn=ISBN)
    embedder = FakeEmbedder()
    summary = env.run(embedder)
    assert (summary.neu, summary.fehler) == (1, 0)

    documents = sorted(env.documents().values(), key=lambda d: d["von_seite"])
    assert len(embedder.texts) == 2
    # Eingebettet werden Titel, Kapitel und Text.
    assert embedder.texts[0].startswith("Ein Buch\nKapitel 1\n")
    for document, text in zip(documents, embedder.texts, strict=True):
        assert document["_vectors"] == {
            "default": {"embeddings": [float(len(text)), 0.0], "regenerate": False}
        }
    assert env.work_files() == []


def test_without_embedder_documents_have_no_vectors(env):
    make_text_pdf(env.settings.books_dir / "text.pdf", pages=1)
    env.run()
    assert all("_vectors" not in d for d in env.documents().values())


def test_failed_embedding_keeps_extraction_for_next_run(env, monkeypatch):
    make_text_pdf(env.settings.books_dir / "text.pdf", pages=2)
    extractions = count_extractions(monkeypatch)

    summary = env.run(FakeEmbedder(fail=True))
    assert (summary.neu, summary.fehler) == (0, 1)
    assert env.state.files()["text.pdf"][1] == STATUS_FEHLER
    assert env.documents() == {}
    assert len(env.work_files()) == 1

    summary = env.run(FakeEmbedder())
    assert (summary.geaendert, summary.fehler) == (1, 0)
    assert extractions == ["text.pdf"]  # nicht noch einmal extrahiert
    assert len(env.documents()) == 2
    assert env.work_files() == []


def test_failed_write_keeps_vectors_for_next_run(env, monkeypatch):
    make_text_pdf(env.settings.books_dir / "text.pdf", pages=2)

    def broken(self, buch_id, documents):
        raise RuntimeError("Meilisearch nicht erreichbar")

    with monkeypatch.context() as patch:
        patch.setattr(SearchIndex, "replace_book", broken)
        first = FakeEmbedder()
        assert env.run(first).fehler == 1
    assert len(first.texts) == 2
    assert len(env.work_files()) == 2

    second = FakeEmbedder()
    assert env.run(second).fehler == 0
    assert second.texts == []  # Vektoren kamen aus der Zwischenablage
    assert all("_vectors" in d for d in env.documents().values())


def test_changed_file_is_extracted_again_despite_old_work_file(env, monkeypatch):
    path = env.settings.books_dir / "text.pdf"
    make_text_pdf(path, pages=3)
    env.run(FakeEmbedder(fail=True))

    make_text_pdf(path, pages=1)
    env.run(FakeEmbedder())
    assert len(env.documents()) == 1


def test_interrupted_after_extraction_is_resumed(env, monkeypatch):
    make_text_pdf(env.settings.books_dir / "text.pdf", pages=1)
    found, _ = pipeline.plan(env.settings, env.state)
    assert pipeline.extract_all(["text.pdf"], found, env.settings, env.state) == {}
    assert env.state.files()["text.pdf"][1] == STATUS_EXTRAHIERT

    extractions = count_extractions(monkeypatch)
    summary = env.run()
    assert (summary.geaendert, summary.uebersprungen) == (1, 0)
    assert extractions == []
    assert env.state.files()["text.pdf"][1] == STATUS_OK


def test_parallel_extraction_with_processes(env):
    books = env.settings.books_dir
    for number in range(4):
        make_text_pdf(books / f"buch{number}.pdf", pages=number + 1)
    (books / "kaputt.pdf").write_bytes(b"das ist keine PDF")

    summary = env.run(settings=replace(env.settings, extract_jobs=2))
    assert (summary.neu, summary.fehler) == (4, 1)
    assert len(env.documents()) == 1 + 2 + 3 + 4
    assert env.state.files()["kaputt.pdf"][1] == STATUS_FEHLER


def test_removed_file_also_leaves_work_dir(env):
    path = env.settings.books_dir / "text.pdf"
    make_text_pdf(path, pages=1)
    env.run(FakeEmbedder(fail=True))
    assert env.work_files()

    path.unlink()
    assert env.run().entfernt == 1
    assert env.work_files() == []
