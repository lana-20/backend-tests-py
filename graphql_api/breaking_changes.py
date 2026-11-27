"""Breaking-change gate for the GraphQL schema.

Compares two SDL files with graphql-core's find_breaking_changes, the same check
GraphQL Inspector and Apollo's schema checks perform. Exit code 1 if anything would
break an existing client (a removed field, a changed type, a new required argument...).

    uv run python -m graphql_api.breaking_changes OLD.graphql NEW.graphql
"""

import sys
from pathlib import Path

from graphql import build_schema, find_breaking_changes, find_dangerous_changes


def breaking_changes(old_sdl: str, new_sdl: str) -> list[str]:
    old, new = build_schema(old_sdl), build_schema(new_sdl)
    return [f"{change.type.name}: {change.description}" for change in find_breaking_changes(old, new)]


def dangerous_changes(old_sdl: str, new_sdl: str) -> list[str]:
    """Not breaking, but can change behavior (e.g. a new enum value clients don't handle)."""
    old, new = build_schema(old_sdl), build_schema(new_sdl)
    return [f"{change.type.name}: {change.description}" for change in find_dangerous_changes(old, new)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    old_sdl, new_sdl = (Path(path).read_text() for path in argv)

    for warning in dangerous_changes(old_sdl, new_sdl):
        print(f"warning: {warning}")
    breaking = breaking_changes(old_sdl, new_sdl)
    for change in breaking:
        print(f"BREAKING {change}")
    print(f"{len(breaking)} breaking change(s)")
    return 1 if breaking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
