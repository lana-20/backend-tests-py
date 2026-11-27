"""Count the SQL statements an engine runs, to catch N+1 queries."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event


@contextmanager
def count_queries(engine: Engine) -> Iterator[list[str]]:
    """Yield a list that collects every SQL statement run inside the block."""
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
