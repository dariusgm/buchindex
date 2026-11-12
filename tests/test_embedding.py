import json
import threading
import time

import httpx
import pytest

from buchindex.embedding import EmbeddingClient, EmbeddingError


class Server:
    """Gemockter Embedding-Endpunkt, der Anfragen und Gleichzeitigkeit mitzählt."""

    def __init__(self, dimensions=3, delay=0.0, drop=0):
        self.requests = []
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()
        self._dimensions, self._delay, self._drop = dimensions, delay, drop

    def __call__(self, request):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(self._delay)
        body = json.loads(request.content)
        self.requests.append((str(request.url), request.headers.get("authorization"), body))
        data = [
            {"index": i, "embedding": [float(len(text))] * self._dimensions}
            for i, text in enumerate(body["input"])
        ]
        with self._lock:
            self._active -= 1
        # Reihenfolge absichtlich umgedreht: maßgeblich ist `index`.
        return httpx.Response(200, json={"data": data[::-1][self._drop :]})

    def client(self, **kwargs):
        http = httpx.Client(transport=httpx.MockTransport(self))
        return EmbeddingClient("http://embed.invalid/v1/", "modell", http=http, **kwargs)


def test_embed_batches_and_keeps_order():
    server = Server()
    texts = ["a" * n for n in range(1, 8)]
    vectors = server.client(batch_size=3).embed(texts)
    assert [v[0] for v in vectors] == [1, 2, 3, 4, 5, 6, 7]
    assert sorted(len(body["input"]) for _, _, body in server.requests) == [1, 3, 3]
    url, _, body = server.requests[0]
    assert url == "http://embed.invalid/v1/embeddings"
    assert body["model"] == "modell"


@pytest.mark.parametrize("parallel", [1, 3])
def test_parallel_limits_concurrent_requests(parallel):
    server = Server(delay=0.05)
    vectors = server.client(batch_size=1, parallel=parallel).embed(
        [str(n) * n for n in range(1, 9)]
    )
    assert [v[0] for v in vectors] == list(range(1, 9))
    assert server.max_active == parallel


def test_wrong_count_or_dimension_raises():
    with pytest.raises(EmbeddingError, match="1 Vektoren für 2 Texte"):
        Server(drop=1).client().embed(["a", "b"])
    with pytest.raises(EmbeddingError, match="3 Dimensionen, erwartet sind 4"):
        Server().client(dimensions=4).embed(["a"])


def test_http_error_raises():
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        EmbeddingClient("http://embed.invalid/v1", "modell", http=http).embed(["a"])


def test_no_texts_no_request():
    server = Server()
    assert server.client().embed([]) == []
    assert server.requests == []
