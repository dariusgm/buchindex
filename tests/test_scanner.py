import os

from buchindex.scanner import diff, fingerprint, scan
from buchindex.state import STATUS_EXTRAHIERT, STATUS_FEHLER, STATUS_OK, StateDB


def test_fingerprint_changes_with_size_and_mtime(tmp_path):
    path = tmp_path / "a.pdf"
    path.write_bytes(b"abc")
    first = fingerprint(path)
    assert fingerprint(path) == first

    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    second = fingerprint(path)
    assert second != first

    path.write_bytes(b"abcdef")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert fingerprint(path) != second


def test_scan_is_recursive_and_filters_suffixes(tmp_path):
    (tmp_path / "unter" / "tiefer").mkdir(parents=True)
    (tmp_path / "a.pdf").write_bytes(b"1")
    (tmp_path / "unter" / "b.EPUB").write_bytes(b"1")
    (tmp_path / "unter" / "tiefer" / "c.pdf").write_bytes(b"1")
    (tmp_path / "notiz.txt").write_bytes(b"1")
    (tmp_path / "ordner.pdf").mkdir()
    assert set(scan(tmp_path)) == {"a.pdf", "unter/b.EPUB", "unter/tiefer/c.pdf"}


def test_diff_categories():
    found = {
        "neu.pdf": "1",
        "gleich.pdf": "2",
        "anders.pdf": "3b",
        "kaputt.pdf": "4",
        "halb.pdf": "6",
    }
    known = {
        "gleich.pdf": ("2", STATUS_OK),
        "anders.pdf": ("3a", STATUS_OK),
        "kaputt.pdf": ("4", STATUS_FEHLER),
        "halb.pdf": ("6", STATUS_EXTRAHIERT),
        "weg.pdf": ("5", STATUS_OK),
    }
    result = diff(found, known)
    assert result.neu == ["neu.pdf"]
    assert result.geaendert == ["anders.pdf", "kaputt.pdf", "halb.pdf"]
    assert result.unveraendert == ["gleich.pdf"]
    assert result.entfernt == ["weg.pdf"]


def test_state_roundtrip(tmp_path):
    with StateDB(tmp_path / "neu" / "state.db") as state:
        state.record("a.pdf", "1", STATUS_OK)
        state.record("b.pdf", "2", STATUS_FEHLER, "kaputt")
        state.record("a.pdf", "1b", STATUS_OK)
        assert state.files() == {"a.pdf": ("1b", STATUS_OK), "b.pdf": ("2", STATUS_FEHLER)}
        assert state.status_counts() == {STATUS_OK: 1, STATUS_FEHLER: 1}
        assert [(p, f) for p, _, f in state.last_errors()] == [("b.pdf", "kaputt")]
        state.remove("b.pdf")
        assert "b.pdf" not in state.files()
