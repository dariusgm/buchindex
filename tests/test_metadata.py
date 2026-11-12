import httpx
import pytest

from buchindex.metadata import Metadata, MetadataClient
from buchindex.state import StateDB

ISBN = "9783161484100"


def make_client(state, handler):
    requests = []

    def recording(request):
        requests.append(str(request.url))
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(recording), follow_redirects=True)
    return MetadataClient(state, http), requests


def open_library(request):
    if request.url.path == f"/isbn/{ISBN}.json":
        return httpx.Response(302, headers={"Location": "/books/OL1M.json"})
    if request.url.path == "/books/OL1M.json":
        return httpx.Response(
            200,
            json={
                "title": "Ein Buch",
                "authors": [{"key": "/authors/OL1A"}, {"key": "/authors/OL2A"}],
                "subjects": ["Linux"],
                "works": [{"key": "/works/OL1W"}],
            },
        )
    if request.url.path == "/works/OL1W.json":
        return httpx.Response(200, json={"subjects": ["linux", "Betriebssysteme"]})
    if request.url.path == "/authors/OL1A.json":
        return httpx.Response(200, json={"name": "Ada Autorin"})
    if request.url.path == "/authors/OL2A.json":
        return httpx.Response(200, json={"name": "Ben Beispiel"})
    return httpx.Response(404)


def test_lookup_and_cache():
    state = StateDB(":memory:")
    client, requests = make_client(state, open_library)
    expected = Metadata(
        titel="Ein Buch", autor="Ada Autorin, Ben Beispiel", kategorie=("Linux", "Betriebssysteme")
    )
    assert client.lookup(ISBN) == expected
    assert requests[0] == f"https://openlibrary.org/isbn/{ISBN}.json"
    count = len(requests)
    assert client.lookup(ISBN) == expected
    assert len(requests) == count


def test_authors_fall_back_to_work():
    def handler(request):
        if request.url.path == f"/isbn/{ISBN}.json":
            return httpx.Response(200, json={"title": "Ein Buch", "works": [{"key": "/works/W"}]})
        if request.url.path == "/works/W.json":
            return httpx.Response(200, json={"authors": [{"author": {"key": "/authors/A"}}]})
        if request.url.path == "/authors/A.json":
            return httpx.Response(200, json={"name": "Ada Autorin"})
        return httpx.Response(404)

    client, _ = make_client(StateDB(":memory:"), handler)
    assert client.lookup(ISBN) == Metadata(titel="Ein Buch", autor="Ada Autorin")


def test_unknown_isbn_is_cached_as_empty():
    state = StateDB(":memory:")
    client, requests = make_client(state, lambda request: httpx.Response(404))
    assert client.lookup(ISBN) == Metadata()
    assert client.lookup(ISBN) == Metadata()
    assert len(requests) == 1


def test_server_error_is_not_cached():
    state = StateDB(":memory:")
    client, requests = make_client(state, lambda request: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        client.lookup(ISBN)
    assert state.cached_isbn(ISBN) == (False, None)
