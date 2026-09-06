"""Shared HTTP runtime for generated connector clients."""
from __future__ import annotations

from typing import Any, Iterator, Mapping, TypeVar

import httpx
from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class RestClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _encode_body(self, body: BaseModel | Mapping[str, Any] | None) -> Any:
        if body is None:
            return None
        if isinstance(body, BaseModel):
            return body.model_dump(mode="json", exclude_none=True)
        return dict(body)

    def _call(
        self,
        verb: str,
        path: str,
        query: Mapping[str, object],
        body: BaseModel | Mapping[str, Any] | None,
        model: type[M] | None,
    ) -> M | None:
        r = self._http.request(
            verb,
            path,
            params={k: v for k, v in query.items() if v is not None},
            json=self._encode_body(body),
        )
        r.raise_for_status()
        if model is None or not r.content:
            return None
        return model.model_validate(r.json())


def cursor_pages(fetch, **query) -> Iterator[Any]:
    """Walk a cursor/next_cursor endpoint. Pagination has no OpenAPI representation."""
    cursor = None
    while True:
        page = fetch(cursor=cursor, **query)
        yield page
        if not (cursor := page.next_cursor):
            return
