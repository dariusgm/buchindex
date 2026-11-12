"""Dünne Schicht über dem Meilisearch-Client."""

from __future__ import annotations

import logging
from typing import Any

import meilisearch
from meilisearch.errors import MeilisearchApiError

from buchindex.config import IndexSettings

log = logging.getLogger(__name__)

TASK_POLL_MS = 500
BATCH_SIZE = 1000


class SearchIndex:
    def __init__(
        self,
        client: meilisearch.Client,
        name: str,
        settings: IndexSettings,
        task_timeout: int = 3600,
    ):
        self._client = client
        self._task_timeout_ms = task_timeout * 1000
        self._name = name
        self._settings = settings
        self._index = client.index(name)

    @classmethod
    def connect(
        cls, url: str, key: str, name: str, settings: IndexSettings, task_timeout: int = 3600
    ) -> SearchIndex:
        return cls(meilisearch.Client(url, key), name, settings, task_timeout)

    def _wait(self, task_info: Any) -> None:
        task = self._client.wait_for_task(
            task_info.task_uid, timeout_in_ms=self._task_timeout_ms, interval_in_ms=TASK_POLL_MS
        )
        if task.status != "succeeded":
            raise RuntimeError(f"Meilisearch-Task {task.uid} ist fehlgeschlagen: {task.error}")

    def check(self) -> None:
        """Prüft Erreichbarkeit und Gültigkeit des Keys. Wirft bei Problemen."""
        self._client.health()
        try:
            self._index.get_stats()
        except MeilisearchApiError as error:
            if error.code != "index_not_found":
                raise

    def ensure_index(self) -> None:
        """Legt den Index beim ersten Lauf an und setzt die Einstellungen."""
        try:
            self._client.get_index(self._name)
            return
        except MeilisearchApiError as error:
            if error.code != "index_not_found":
                raise
        log.info("Lege Index %r an", self._name)
        self._wait(self._client.create_index(self._name, {"primaryKey": "id"}))
        self._wait(self._index.update_settings(self._settings.to_meili()))

    def delete_book(self, buch_id: str) -> None:
        self._wait(self._index.delete_documents(filter=f'buch_id = "{buch_id}"'))

    def replace_book(self, buch_id: str, documents: list[dict[str, Any]]) -> None:
        """Löscht alle alten Passagen des Buchs und schreibt die neuen."""
        self.delete_book(buch_id)
        for start in range(0, len(documents), BATCH_SIZE):
            self._wait(self._index.add_documents(documents[start : start + BATCH_SIZE], "id"))
