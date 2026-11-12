import os
import uuid

import pytest

from buchindex.config import IndexSettings
from buchindex.search import SearchIndex

from .fakes import FakeClient, api_error


def doc(doc_id, buch_id, text="t"):
    return {"id": doc_id, "buch_id": buch_id, "text": text, "pdf_seite": 1}


def test_ensure_index_sets_settings_only_on_first_run():
    client = FakeClient()
    index = SearchIndex(client, "test", IndexSettings())
    index.ensure_index()
    assert client.indexes["test"]["settings"] == IndexSettings().to_meili()
    assert client.calls == ["create", "settings"]
    index.ensure_index()
    assert client.calls == ["create", "settings"]


def test_replace_book_removes_old_passages():
    client = FakeClient()
    index = SearchIndex(client, "test", IndexSettings())
    index.ensure_index()
    index.replace_book("aa", [doc("1", "aa"), doc("2", "aa"), doc("3", "aa")])
    index.replace_book("bb", [doc("4", "bb")])
    index.replace_book("aa", [doc("1", "aa", "neu")])
    documents = client.indexes["test"]["documents"]
    assert set(documents) == {"1", "4"}
    assert documents["1"]["text"] == "neu"


def test_failed_task_raises():
    client = FakeClient()
    index = SearchIndex(client, "test", IndexSettings())
    index.ensure_index()
    client.wait_for_task = lambda uid, **kwargs: type(
        "Task", (), {"uid": uid, "status": "failed", "error": {"code": "kaputt"}}
    )()
    with pytest.raises(RuntimeError, match="kaputt"):
        index.delete_book("aa")


def test_check_accepts_missing_index_but_not_invalid_key():
    client = FakeClient()
    index = SearchIndex(client, "test", IndexSettings())
    index.check()

    def invalid_key(uid):
        raise api_error("invalid_api_key", 403)

    client.require = invalid_key
    with pytest.raises(Exception, match="invalid_api_key"):
        index.check()


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("MEILI_URL"), reason="MEILI_URL ist nicht gesetzt")
def test_integration_with_real_meilisearch():
    import meilisearch

    client = meilisearch.Client(os.environ["MEILI_URL"], os.environ.get("MEILI_KEY"))
    name = f"buchindex_test_{uuid.uuid4().hex}"
    index = SearchIndex(client, name, IndexSettings())
    try:
        index.check()
        index.ensure_index()
        index.ensure_index()
        settings = client.index(name).get_settings()
        assert sorted(settings["filterableAttributes"]) == [
            "autor",
            "buch_id",
            "kapitel",
            "kategorie",
        ]
        assert settings["sortableAttributes"] == ["pdf_seite"]
        assert settings["searchableAttributes"] == ["text", "titel", "kapitel"]

        index.replace_book("aa", [doc("1", "aa", "Apfel"), doc("2", "aa", "Birne")])
        index.replace_book("bb", [doc("3", "bb", "Kirsche")])
        index.replace_book("aa", [doc("1", "aa", "Pflaume")])
        assert client.index(name).get_stats().number_of_documents == 2
        hits = client.index(name).search("Pflaume", {"sort": ["pdf_seite:asc"]})["hits"]
        assert [hit["id"] for hit in hits] == ["1"]
        index.delete_book("bb")
        assert client.index(name).get_stats().number_of_documents == 1
    finally:
        client.wait_for_task(client.delete_index(name).task_uid)
