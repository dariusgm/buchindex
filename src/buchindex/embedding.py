"""Client für einen OpenAI-kompatiblen Embedding-Endpunkt (`<url>/embeddings`)."""

from __future__ import annotations

import httpx
from joblib import Parallel, delayed


class EmbeddingError(RuntimeError):
    """Der Embedding-Server hat nicht die erwartete Antwort geliefert."""


class EmbeddingClient:
    """Berechnet Vektoren für Texte.

    `parallel` begrenzt die gleichzeitig offenen Anfragen an den Server,
    `batch_size` die Zahl der Texte pro Anfrage.
    """

    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        dimensions: int | None = None,
        parallel: int = 1,
        batch_size: int = 8,
        timeout: float = 300,
        http: httpx.Client | None = None,
    ):
        self._url = url.rstrip("/") + "/embeddings"
        self.model = model
        self._dimensions = dimensions
        self._parallel = parallel
        self._batch_size = batch_size
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.Client(timeout=timeout, headers=headers)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._http.post(self._url, json={"model": self.model, "input": texts})
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"Embedding-Server lieferte {len(vectors)} Vektoren für {len(texts)} Texte."
            )
        for vector in vectors:
            if self._dimensions and len(vector) != self._dimensions:
                raise EmbeddingError(
                    f"Vektor hat {len(vector)} Dimensionen, erwartet sind {self._dimensions}."
                )
        return vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Liefert zu jedem Text einen Vektor, in der Reihenfolge der Texte."""
        batches = [
            texts[start : start + self._batch_size]
            for start in range(0, len(texts), self._batch_size)
        ]
        # Threads genügen: Die Arbeit macht der Server, hier wird nur gewartet.
        results = Parallel(n_jobs=self._parallel, prefer="threads")(
            delayed(self._embed_batch)(batch) for batch in batches
        )
        return [vector for batch in results for vector in batch]
