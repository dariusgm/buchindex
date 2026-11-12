import shutil
import subprocess

import pytest

from buchindex import epub
from buchindex.chunking import chunk

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc fehlt")


def test_epub_chapters(tmp_path):
    source = tmp_path / "buch.md"
    source.write_text(
        "---\ntitle: Testbuch\n---\n\n# Erstes Kapitel\n\nText eins.\n\n"
        "## Unterkapitel\n\nText zwei.\n\n# Zweites Kapitel\n\nText drei.\n",
        encoding="utf-8",
    )
    target = tmp_path / "buch.epub"
    subprocess.run(["pandoc", str(source), "-o", str(target)], check=True)

    passages = chunk([(None, epub.to_markdown(target))], 1500)
    by_chapter = {p.kapitel: p.text for p in passages}
    assert by_chapter["Erstes Kapitel"] == "Text eins."
    assert by_chapter["Erstes Kapitel > Unterkapitel"] == "Text zwei."
    assert by_chapter["Zweites Kapitel"] == "Text drei."
    assert all(p.von_seite is None for p in passages)
