from buchindex.chunking import book_id, chunk, document_id


def test_splits_at_headings_with_hierarchy():
    markdown = (
        "Vorwort ohne Überschrift.\n\n# Teil 1\n\nEinleitung.\n\n## **Kapitel A**\n\nText A.\n\n"
        "## Kapitel B\n\nText B.\n\n# Teil 2\n\nText 2."
    )
    passages = chunk([(None, markdown)], 1500)
    assert [(p.kapitel, p.text) for p in passages] == [
        (None, "Vorwort ohne Überschrift."),
        ("Teil 1", "Einleitung."),
        ("Teil 1 > Kapitel A", "Text A."),
        ("Teil 1 > Kapitel B", "Text B."),
        ("Teil 2", "Text 2."),
    ]


def test_long_section_is_split_at_paragraphs():
    paragraphs = [f"Absatz {n}. " + "x" * 80 for n in range(10)]
    passages = chunk([(1, "# Kapitel\n\n" + "\n\n".join(paragraphs))], 200)
    assert len(passages) == 5
    assert all(len(p.text) <= 200 for p in passages)
    assert all(p.kapitel == "Kapitel" for p in passages)
    assert "\n\n".join(p.text for p in passages) == "\n\n".join(paragraphs)


def test_oversized_paragraph_respects_limit():
    passages = chunk([(1, "wort " * 200)], 100)
    assert len(passages) > 1
    assert all(len(p.text) <= 100 for p in passages)


def test_page_ranges():
    pages = [
        (1, "# Kapitel 1\n\n" + "a" * 60),
        (2, "b" * 60),
        (3, "c" * 60 + "\n\n# Kapitel 2\n\nEnde."),
    ]
    passages = chunk(pages, 150)
    assert [(p.kapitel, p.von_seite, p.bis_seite) for p in passages] == [
        ("Kapitel 1", 1, 2),
        ("Kapitel 1", 3, 3),
        ("Kapitel 2", 3, 3),
    ]


def test_heading_in_code_block_is_ignored():
    passages = chunk([(1, "# Kapitel\n\n```\n# Kommentar\n\ncode\n```\n\nText.")], 1500)
    assert [p.kapitel for p in passages] == ["Kapitel"]
    assert "# Kommentar" in passages[0].text


def test_empty_input():
    assert chunk([(1, ""), (2, "\n\n")], 100) == []


def test_document_ids_are_stable_and_unique():
    assert document_id("a/b.pdf", 0) == document_id("a/b.pdf", 0)
    assert document_id("a/b.pdf", 0) != document_id("a/b.pdf", 1)
    assert document_id("a/b.pdf", 0) != document_id("a/c.pdf", 0)
    assert document_id("a.pdf", 11) != document_id("a.pdf1", 1)
    assert document_id("ä/ö.pdf", 3).isalnum()
    assert book_id("a/b.pdf") == book_id("a/b.pdf") != book_id("a/c.pdf")


def test_document_id_known_value():
    # Schützt vor versehentlichen Änderungen am Hash, die alle IDs verschieben würden.
    assert document_id("a/b.pdf", 0) == "ae5108dadc38aebe0689d4d9474b4df1"


def test_heading_markup_is_removed():
    markdown = (
        "# <u>I. Allgemeines</u>\n\nA.\n\n## [Teil\xa0II, **Ereignisse**](#part02.html)\n\nB."
    )
    assert [p.kapitel for p in chunk([(1, markdown)], 1500)] == [
        "I. Allgemeines",
        "I. Allgemeines > Teil II, Ereignisse",
    ]
