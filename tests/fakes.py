"""Speicherinterner Ersatz für meilisearch.Client."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from meilisearch.errors import MeilisearchApiError
from requests import Response


def api_error(code: str, status: int = 404) -> MeilisearchApiError:
    response = Response()
    response.status_code = status
    response._content = json.dumps({"message": code, "code": code}).encode()
    return MeilisearchApiError(code, response)


class FakeIndex:
    def __init__(self, client: FakeClient, uid: str):
        self._client = client
        self.uid = uid

    @property
    def documents(self) -> dict[str, dict]:
        return self._client.indexes[self.uid]["documents"]

    def get_stats(self):
        self._client.require(self.uid)
        return SimpleNamespace(number_of_documents=len(self.documents))

    def update_settings(self, settings):
        self._client.indexes[self.uid]["settings"] = settings
        return self._client.task("settings")

    def delete_documents(self, ids=None, *, filter=None):
        match = re.fullmatch(r'buch_id = "([0-9a-f]+)"', filter)
        assert match, f"unerwarteter Filter: {filter}"
        for doc_id in [k for k, d in self.documents.items() if d["buch_id"] == match.group(1)]:
            del self.documents[doc_id]
        return self._client.task("delete")

    def add_documents(self, documents, primary_key=None):
        assert primary_key == "id"
        for document in documents:
            self.documents[document["id"]] = dict(document)
        return self._client.task("add")


class FakeClient:
    def __init__(self):
        self.indexes: dict[str, dict] = {}
        self.calls: list[str] = []

    def task(self, kind: str):
        self.calls.append(kind)
        return SimpleNamespace(task_uid=len(self.calls))

    def require(self, uid: str) -> None:
        if uid not in self.indexes:
            raise api_error("index_not_found")

    def health(self):
        return {"status": "available"}

    def index(self, uid: str) -> FakeIndex:
        return FakeIndex(self, uid)

    def get_index(self, uid: str) -> FakeIndex:
        self.require(uid)
        return FakeIndex(self, uid)

    def create_index(self, uid: str, options=None):
        assert options == {"primaryKey": "id"}
        self.indexes[uid] = {"documents": {}, "settings": None}
        return self.task("create")

    def wait_for_task(self, uid, timeout_in_ms=5000, interval_in_ms=50):
        return SimpleNamespace(uid=uid, status="succeeded", error=None)
