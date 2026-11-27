"""Alembic environment: runs migrations on the engine passed in by the caller.

`render_as_batch=True` makes Alembic use "batch mode" on SQLite, which can't ALTER most
things in place: it copies the table, applies the change, and swaps the copy in. On the
other engines batch mode just emits normal ALTER statements.
"""

from alembic import context

from sql_engines.app.models import Base

engine = context.config.attributes["engine"]

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
