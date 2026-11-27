"""Cursor pagination: walk every page, and reject bad page requests."""

from typing import Any

import pytest

from graphql_api.app.schema import MAX_PAGE_SIZE
from graphql_api.tests.client import GraphQLClient

PAGE = """
query Page($first: Int!, $after: String) {
  contacts(first: $first, after: $after) {
    edges { cursor node { id } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def fetch_page(api: GraphQLClient, first: int, after: str | None) -> dict[str, Any]:
    response = api.execute(PAGE, {"first": first, "after": after}, token="admin-token")
    assert response.errors == []
    page: dict[str, Any] = response.data["contacts"]
    return page


def test_walking_every_page_returns_each_contact_once(api: GraphQLClient) -> None:
    seen: list[str] = []
    page_sizes: list[int] = []
    after = None
    while True:
        page = fetch_page(api, first=2, after=after)
        ids = [edge["node"]["id"] for edge in page["edges"]]
        seen += ids
        page_sizes.append(len(ids))
        # The cursor of the page is the cursor of its last edge.
        assert page["pageInfo"]["endCursor"] == page["edges"][-1]["cursor"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    assert page_sizes == [2, 2, 1]
    assert seen == ["1", "2", "3", "4", "5"]  # all of them, in order, no repeats


def test_page_after_the_last_one_is_empty(api: GraphQLClient) -> None:
    last = fetch_page(api, first=5, after=None)
    assert last["pageInfo"]["hasNextPage"] is False

    beyond = fetch_page(api, first=5, after=last["pageInfo"]["endCursor"])
    assert beyond == {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}


@pytest.mark.parametrize("first", [0, -1, MAX_PAGE_SIZE + 1])
def test_page_size_is_bounded(api: GraphQLClient, first: int) -> None:
    response = api.execute(PAGE, {"first": first}, token="admin-token")
    assert response.error_codes == ["BAD_USER_INPUT"]
    assert response.data is None
