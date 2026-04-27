"""Thin wrapper around Sanity's GROQ HTTP API.

Loads project ID, dataset, API version, and bearer token from `.env`.
Exposes `query()` and `mutate()` helpers. Read-only by default; mutations
are explicit via `mutate()`.

Usage:
    from execution.sanity_client import SanityClient

    client = SanityClient()
    results = client.query('*[_type == "post"][0...3]{_id, title}')
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class SanityConfigError(RuntimeError):
    pass


class SanityQueryError(RuntimeError):
    def __init__(self, status: int, body: str, query: str):
        super().__init__(f"Sanity query failed ({status}): {body[:300]}")
        self.status = status
        self.body = body
        self.query = query


class SanityClient:
    def __init__(
        self,
        project_id: str | None = None,
        dataset: str | None = None,
        api_version: str | None = None,
        token: str | None = None,
        default_perspective: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.project_id = project_id or os.environ.get("SANITY_PROJECT_ID")
        self.dataset = dataset or os.environ.get("SANITY_DATASET")
        self.api_version = api_version or os.environ.get("SANITY_API_VERSION")
        self.token = token or os.environ.get("SANITY_TOKEN")
        self.default_perspective = (
            default_perspective
            or os.environ.get("SANITY_DEFAULT_PERSPECTIVE")
            or "published"
        )
        self.timeout = timeout_seconds

        for name, value in (
            ("SANITY_PROJECT_ID", self.project_id),
            ("SANITY_DATASET", self.dataset),
            ("SANITY_API_VERSION", self.api_version),
            ("SANITY_TOKEN", self.token),
        ):
            if not value:
                raise SanityConfigError(f"Missing {name} in environment / .env")

    @property
    def base_url(self) -> str:
        return f"https://{self.project_id}.api.sanity.io/{self.api_version}"

    def query(
        self,
        groq: str,
        params: dict[str, Any] | None = None,
        perspective: str | None = None,
    ) -> Any:
        """Run a GROQ query. Returns the parsed `result` from the response."""
        url = f"{self.base_url}/data/query/{self.dataset}"
        query_params: list[tuple[str, str]] = [("query", groq)]
        for key, value in (params or {}).items():
            query_params.append((f"${key}", _encode_param(value)))
        query_params.append(("perspective", perspective or self.default_perspective))

        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(
            url, params=query_params, headers=headers, timeout=self.timeout
        )
        if response.status_code != 200:
            raise SanityQueryError(response.status_code, response.text, groq)
        body = response.json()
        return body.get("result")

    def fetch_one(self, groq: str, params: dict[str, Any] | None = None) -> Any:
        results = self.query(groq, params=params)
        if isinstance(results, list):
            return results[0] if results else None
        return results

    def list_document_types(self, limit: int = 50) -> list[str]:
        """Quick discovery helper — returns distinct `_type` values."""
        groq = (
            "array::unique(*[!(_type match 'system.*') "
            "&& !(_type in ['sanity.imageAsset','sanity.fileAsset'])]"
            f"._type) [0...{limit}]"
        )
        return self.query(groq) or []


def _encode_param(value: Any) -> str:
    """Sanity's GET query API expects param values JSON-encoded."""
    import json

    return json.dumps(value, ensure_ascii=False)


__all__ = ["SanityClient", "SanityConfigError", "SanityQueryError"]
