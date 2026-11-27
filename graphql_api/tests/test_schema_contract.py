"""The schema is a contract: it is checked into git, and changes to it are reviewed."""

from pathlib import Path

from graphql_api.app.schema import schema

SDL_FILE = Path(__file__).resolve().parent.parent / "schema.graphql"


def test_committed_sdl_matches_the_code() -> None:
    """Fails when the code's schema drifts from schema.graphql.

    If the change is intended, regenerate the file and commit it, so the diff shows up
    in review and the breaking-change gate in CI can compare it with the base branch:

        uv run python -m graphql_api.app.schema > graphql_api/schema.graphql
    """
    assert schema.as_str() + "\n" == SDL_FILE.read_text()
