import shutil

import pytest

from buchindex import pdf

from .conftest import make_empty_pdf, make_text_pdf


def test_text_pdf_needs_no_ocr(tmp_path):
    path = make_text_pdf(tmp_path / "text.pdf")
    assert pdf.chars_per_page(path) > 50
    assert not pdf.needs_ocr(path, 50)


def test_empty_pdf_needs_ocr(tmp_path):
    path = make_empty_pdf(tmp_path / "scan.pdf")
    assert pdf.chars_per_page(path) == 0
    assert pdf.needs_ocr(path, 50)


def test_threshold_is_average_per_page(tmp_path):
    path = make_text_pdf(tmp_path / "text.pdf", pages=2)
    average = pdf.chars_per_page(path)
    assert not pdf.needs_ocr(path, int(average))
    assert pdf.needs_ocr(path, int(average) + 1)


def test_markdown_pages_keep_page_numbers(tmp_path, capsys):
    path = make_text_pdf(tmp_path / "text.pdf", pages=3)
    pages = pdf.to_markdown_pages(path)
    assert [number for number, _ in pages] == [1, 2, 3]
    for number, text in pages:
        assert f"Inhalt von Seite {number}." in text
        assert f"Kapitel {number}" in text
    assert capsys.readouterr().out == ""


def test_extract_uses_ocr_copy_and_leaves_original_untouched(tmp_path, monkeypatch):
    source = make_empty_pdf(tmp_path / "scan.pdf")
    before = source.read_bytes()
    targets = []

    def fake_ocr(src, target, lang):
        assert (src, lang) == (source, "deu")
        assert target.parent != source.parent
        targets.append(target)
        make_text_pdf(target, pages=2)

    monkeypatch.setattr(pdf, "ocr_copy", fake_ocr)
    pages = pdf.extract_pages(source, 50, "deu")
    assert [number for number, _ in pages] == [1, 2]
    assert source.read_bytes() == before
    assert not targets[0].exists()


@pytest.mark.skipif(
    not all(shutil.which(p) for p in ("tesseract", "gs", "qpdf")),
    reason="tesseract, ghostscript oder qpdf fehlt",
)
def test_real_ocr(tmp_path):
    import pymupdf

    # Text als Bild rendern, damit eine PDF ohne Textebene entsteht.
    text_pdf = make_text_pdf(tmp_path / "text.pdf", pages=1)
    with pymupdf.open(text_pdf) as doc:
        pixmap = doc[0].get_pixmap(dpi=200)
    scan = pymupdf.open()
    page = scan.new_page()
    page.insert_image(page.rect, pixmap=pixmap)
    scan.save(tmp_path / "scan.pdf")
    scan.close()

    assert pdf.needs_ocr(tmp_path / "scan.pdf", 50)
    pages = pdf.extract_pages(tmp_path / "scan.pdf", 50, "eng")
    assert "Inhalt" in pages[0][1]


def test_clean_markdown_removes_picture_markers():
    marked = "<!-- Start of picture text -->\nK<br>y = f(x)<br>k=1<br><!-- End of picture text -->"
    raw = f"Davor\n\n{marked}\n\nDanach"
    assert pdf.clean_markdown(raw) == "Davor\n\nK y = f(x) k=1\n\nDanach"
