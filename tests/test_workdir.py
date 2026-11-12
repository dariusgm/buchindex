from buchindex.chunking import Passage
from buchindex.workdir import WorkDir

PASSAGES = [Passage("Kapitel 1", 1, 2, "Text ä"), Passage(None, None, None, "ohne Seite")]


def test_extraction_roundtrip_depends_on_fingerprint(tmp_path):
    work = WorkDir(tmp_path / "neu" / "work")
    assert work.load_extraction("a.pdf", "1") is None
    work.save_extraction("a.pdf", "1", "9783161484100", PASSAGES)

    extraction = work.load_extraction("a.pdf", "1")
    assert extraction.isbn == "9783161484100"
    assert extraction.passages == PASSAGES
    assert work.load_extraction("a.pdf", "2") is None
    assert work.load_extraction("b.pdf", "1") is None


def test_vectors_depend_on_fingerprint_model_and_count(tmp_path):
    work = WorkDir(tmp_path)
    work.save_vectors("a.pdf", "1", "modell", [[0.1, 0.2], [0.3, 0.4]])
    assert work.load_vectors("a.pdf", "1", "modell", 2) == [[0.1, 0.2], [0.3, 0.4]]
    assert work.load_vectors("a.pdf", "2", "modell", 2) is None
    assert work.load_vectors("a.pdf", "1", "anderes", 2) is None
    assert work.load_vectors("a.pdf", "1", "modell", 3) is None


def test_broken_file_counts_as_missing_and_discard_removes_everything(tmp_path):
    work = WorkDir(tmp_path)
    work.save_extraction("a.pdf", "1", None, PASSAGES)
    work.save_vectors("a.pdf", "1", "modell", [[0.1], [0.2]])
    next(tmp_path.glob("*.passagen.json")).write_text("{halb", encoding="utf-8")
    assert work.load_extraction("a.pdf", "1") is None

    work.discard("a.pdf")
    work.discard("a.pdf")  # zweimal ist kein Fehler
    assert list(tmp_path.iterdir()) == []
