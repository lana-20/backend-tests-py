"""Alembic migrations: they apply, they reverse, and they produce what the models expect.

Each test gets a brand-new database, so it starts from an empty schema.
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from sql_engines.app.database import downgrade, upgrade
from sql_engines.app.models import Base
from sql_engines.tests.conftest import SqlTarget


def fresh_database(sql: SqlTarget) -> sa.Engine:
    # A new database per test; the container is thrown away at the end, so no cleanup.
    return sql.server.create_database(f"mig_{uuid4().hex[:12]}")


def tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names()) - {"alembic_version"}


def columns(engine: sa.Engine, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(engine).get_columns(table)}


def test_upgrade_downgrade_upgrade(sql: SqlTarget) -> None:
    engine = fresh_database(sql)

    upgrade(engine, "head")
    assert tables(engine) == {"products", "orders"}
    assert "version" in columns(engine, "products")

    # One step back: orders is gone, and products lost the column 0002 added.
    downgrade(engine, "0001")
    assert tables(engine) == {"products"}
    assert "version" not in columns(engine, "products")

    downgrade(engine, "base")
    assert tables(engine) == set()

    # Up again: a downgrade that leaves debris (a stray constraint, an index) fails here.
    upgrade(engine, "head")
    assert tables(engine) == {"products", "orders"}
    engine.dispose()


def test_upgrade_keeps_existing_rows(sql: SqlTarget) -> None:
    """0002 adds a NOT NULL column to a table that already has rows."""
    engine = fresh_database(sql)
    upgrade(engine, "0001")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO products (sku, name, price_cents, stock) VALUES ('OLD-1', 'Old', 100, 5)"))

    upgrade(engine, "head")

    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT sku, stock, version FROM products")).one()
    assert tuple(row) == ("OLD-1", 5, 1)
    engine.dispose()


def test_models_match_migrated_schema(sql: SqlTarget) -> None:
    """The ORM models and the migrations describe the same schema.

    This is what `alembic revision --autogenerate` would compare. An empty diff means no
    one changed a model without writing a migration (or the other way round).
    """
    engine = fresh_database(sql)
    upgrade(engine, "head")

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == []
    engine.dispose()
