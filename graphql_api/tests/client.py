"""A minimal GraphQL-over-HTTP client: one POST, JSON in, JSON out.

Deliberately thin, so every test shows exactly what goes over the wire.
"""

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class GraphQLResponse:
    status: int
    body: dict[str, Any]

    @property
    def data(self) -> Any:
        return self.body.get("data")

    @property
    def errors(self) -> list[dict[str, Any]]:
        return list(self.body.get("errors", []))

    @property
    def error_codes(self) -> list[str]:
        return [error.get("extensions", {}).get("code") for error in self.errors]


class GraphQLClient:
    def __init__(self, url: str) -> None:
        self.url = url

    def execute(self, query: str, variables: dict[str, Any] | None = None, token: str | None = None) -> GraphQLResponse:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.post(
            self.url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=10
        )
        return GraphQLResponse(response.status_code, response.json())
