import pytest

from buchindex.isbn import find_isbn, is_valid_isbn10, is_valid_isbn13


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ISBN 978-3-16-148410-0", "9783161484100"),
        ("ISBN-13: 9783161484100", "9783161484100"),
        ("ISBN 978 3 16 148410 0 gedruckt", "9783161484100"),
        ("ISBN 3-16-148410-X", "316148410X"),
        ("isbn: 0306406152", "0306406152"),
        ("ISBN 0-306-40615-2 und ISBN 978-0-306-40615-7", "9780306406157"),
    ],
)
def test_finds_valid_isbn(text, expected):
    assert find_isbn(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "kein Treffer",
        "ISBN 978-3-16-148410-1",  # falsche Prüfziffer
        "ISBN 3-16-148410-1",  # falsche Prüfziffer
        "Telefon 12345",
        "Bestellnummer 97831614841001234",  # zu lang
    ],
)
def test_rejects_invalid_isbn(text):
    assert find_isbn(text) is None


def test_checksums():
    assert is_valid_isbn13("9783161484100")
    assert not is_valid_isbn13("9783161484101")
    assert not is_valid_isbn13("1234567890123")
    assert is_valid_isbn10("316148410X")
    assert not is_valid_isbn10("3161484100")
