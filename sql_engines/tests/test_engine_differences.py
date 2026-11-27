"""Where the four engines disagree, written down as tests.

Each test states the expected behavior per engine in a dict at the top, so a reader can
see the difference at a glance, and CI proves the dict is still true. An engine-specific
feature that doesn't exist elsewhere is a skip with a reason, never a silent pass.
"""

import sqlite3
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from sql_engines.app.models import Product
from sql_engines.app.models import products_table as products
from sql_engines.app.repository import build_upsert, cheapest_products, select_product_for_update, upsert_product
from sql_engines.tests.conftest import SqlTarget


def insert_product(conn: sa.Connection, sku: str, name: str = "Widget") -> None:
    conn.execute(sa.insert(products).values(sku=sku, name=name, price_cents=100, stock=10))


# --- Isolation -------------------------------------------------------------------------

DEFAULT_ISOLATION = {
    "postgres": ("SHOW transaction_isolation", "read committed"),
    "mysql": ("SELECT @@transaction_isolation", "REPEATABLE-READ"),
    # 2 = READ COMMITTED. (Azure SQL Database also turns on READ_COMMITTED_SNAPSHOT by
    # default; a boxed SQL Server like this one does not.)
    "mssql": ("SELECT transaction_isolation_level FROM sys.dm_exec_sessions WHERE session_id = @@SPID", 2),
    # SQLite transactions are serializable: one writer at a time, for the whole file.
    # read_uncommitted = 0 means no dirty reads even across connections sharing a cache.
    "sqlite": ("PRAGMA read_uncommitted", 0),
}


def test_default_isolation_level(sql: SqlTarget, db: sa.Connection) -> None:
    query, expected = DEFAULT_ISOLATION[sql.key]
    assert db.exec_driver_sql(query).scalar_one() == expected


@pytest.fixture
def committed_sku(sql: SqlTarget) -> Iterator[str]:
    sku = f"ISO-{uuid4().hex[:8]}"
    with sql.engine.begin() as conn:
        insert_product(conn, sku)
    yield sku
    with sql.engine.begin() as conn:
        conn.execute(sa.delete(products).where(products.c.sku == sku))


def read_stock_without_waiting(sql: SqlTarget, reader: sa.Connection, sku: str) -> str:
    """Read the stock; report "blocked" instead of waiting if a lock is in the way."""
    if sql.key == "mssql":
        reader.exec_driver_sql("SET LOCK_TIMEOUT 0")  # fail at once instead of waiting
    try:
        stock = reader.execute(sa.select(products.c.stock).where(products.c.sku == sku)).scalar_one()
        return f"reads {stock}"
    except OperationalError:
        return "blocked"
    finally:
        if sql.key == "mssql":
            reader.exec_driver_sql("SET LOCK_TIMEOUT 5000")  # pooled connection: restore


# Writer has changed stock 10 -> 0 but not committed. What does a plain reader see?
READER_VS_UNCOMMITTED_WRITE = {
    "postgres": "reads 10",  # MVCC: readers see the last committed version
    "mysql": "reads 10",  # InnoDB consistent (snapshot) read
    "mssql": "blocked",  # locking READ COMMITTED: the reader waits for the writer's lock
    "sqlite": "reads 10",  # writer holds RESERVED; readers may still read the old pages
}


def test_reader_and_an_uncommitted_write(sql: SqlTarget, committed_sku: str) -> None:
    with sql.engine.connect() as writer, sql.engine.connect() as reader:
        writer.execute(sa.update(products).where(products.c.sku == committed_sku).values(stock=0))
        outcome = read_stock_without_waiting(sql, reader, committed_sku)
        writer.rollback()
        reader.rollback()

    assert outcome == READER_VS_UNCOMMITTED_WRITE[sql.key]


def test_sql_server_snapshot_isolation_lets_readers_through(sql: SqlTarget, committed_sku: str) -> None:
    """SQL Server's opt-in row versioning: the fix for "readers block on writers"."""
    if sql.key != "mssql":
        pytest.skip("SNAPSHOT is a SQL Server option; the other engines' readers never block on writers")

    with (
        sql.engine.connect() as writer,
        sql.engine.connect().execution_options(isolation_level="SNAPSHOT") as reader,
    ):
        writer.execute(sa.update(products).where(products.c.sku == committed_sku).values(stock=0))
        outcome = read_stock_without_waiting(sql, reader, committed_sku)
        writer.rollback()
        reader.rollback()

    # Needs ALLOW_SNAPSHOT_ISOLATION ON for the database (servers.py turns it on).
    # READ_COMMITTED_SNAPSHOT ON would do this for every default transaction instead.
    assert outcome == "reads 10"


# --- Collation and Unicode -------------------------------------------------------------

# Default collations: MySQL 8 uses utf8mb4_0900_ai_ci and SQL Server
# SQL_Latin1_General_CP1_CI_AS. "ci" = case-insensitive. PostgreSQL and SQLite compare
# bytes by default.
CASE_INSENSITIVE_BY_DEFAULT = {"postgres": False, "mysql": True, "mssql": True, "sqlite": False}


def test_string_equality_and_case(sql: SqlTarget, db: sa.Connection) -> None:
    insert_product(db, "Case-1")
    matches = db.execute(sa.text("SELECT COUNT(*) FROM products WHERE sku = 'case-1'")).scalar_one()
    assert (matches == 1) is CASE_INSENSITIVE_BY_DEFAULT[sql.key]


def test_unique_constraint_and_case(sql: SqlTarget, db: sa.Connection) -> None:
    """The same collation decides whether 'Case-1' and 'CASE-1' are duplicates."""
    insert_product(db, "Case-1")
    if CASE_INSENSITIVE_BY_DEFAULT[sql.key]:
        with pytest.raises(IntegrityError), db.begin_nested():
            insert_product(db, "CASE-1")
    else:
        insert_product(db, "CASE-1")
        assert db.execute(sa.text("SELECT COUNT(*) FROM products")).scalar_one() == 2


def test_unicode_round_trip(sql: SqlTarget, db: sa.Connection) -> None:
    name = "Zoë's 李 notebook 🚀"
    insert_product(db, "UNI-1", name=name)
    assert db.execute(sa.text("SELECT name FROM products WHERE sku = 'UNI-1'")).scalar_one() == name

    # The model says Unicode(100). Only SQL Server needs a different type for it.
    column_type = next(c["type"] for c in sa.inspect(db).get_columns("products") if c["name"] == "name")
    expected_type = "NVARCHAR" if sql.key == "mssql" else "VARCHAR"
    assert type(column_type).__name__ == expected_type


def test_sql_server_varchar_loses_characters(sql: SqlTarget, db: sa.Connection) -> None:
    """Why NVARCHAR: SQL Server's VARCHAR uses the collation's 8-bit code page."""
    if sql.key != "mssql":
        pytest.skip("SQL Server-only: the other engines' VARCHAR stores UTF-8 text")
    assert db.exec_driver_sql("SELECT CAST(N'李' AS VARCHAR(10))").scalar_one() == "?"
    assert db.exec_driver_sql("SELECT CAST(N'李' AS NVARCHAR(10))").scalar_one() == "李"


# --- Dialect syntax --------------------------------------------------------------------

LIMIT_KEYWORD = {"postgres": "LIMIT", "mysql": "LIMIT", "mssql": "TOP", "sqlite": "LIMIT"}


def test_limit_is_top_on_sql_server(sql: SqlTarget, seeded: Session) -> None:
    query = cheapest_products(2)
    assert LIMIT_KEYWORD[sql.key] in str(query.compile(dialect=sql.engine.dialect))
    assert seeded.scalars(query).all() == ["SKU-002", "SKU-001"]


IDENTITY_DDL = {
    "postgres": "GENERATED BY DEFAULT AS IDENTITY",
    "mysql": "AUTO_INCREMENT",
    "mssql": "IDENTITY",
    # An INTEGER PRIMARY KEY becomes an alias for SQLite's built-in rowid.
    "sqlite": "id INTEGER NOT NULL",
}
# Can the application insert its own value into the identity column?
EXPLICIT_ID_ACCEPTED = {"postgres": True, "mysql": True, "mssql": False, "sqlite": True}


def test_identity_columns(sql: SqlTarget, db: sa.Connection) -> None:
    ddl = str(CreateTable(products).compile(dialect=sql.engine.dialect))
    assert IDENTITY_DDL[sql.key] in ddl

    explicit = sa.insert(products).values(id=1000, sku="ID-1", name="Explicit", price_cents=1, stock=1)
    if EXPLICIT_ID_ACCEPTED[sql.key]:
        db.execute(explicit)
        # PostgreSQL caveat: the sequence did not move, so a later generated id can
        # collide with 1000. Data loads must call setval() afterwards.
    else:
        # SQL Server needs SET IDENTITY_INSERT products ON first.
        with pytest.raises(DBAPIError, match="IDENTITY_INSERT"), db.begin_nested():
            db.execute(explicit)


UPSERT_KEYWORD = {
    "postgres": "ON CONFLICT",
    "sqlite": "ON CONFLICT",
    "mysql": "ON DUPLICATE KEY UPDATE",
    "mssql": "MERGE",
}


def test_upsert(sql: SqlTarget, db: sa.Connection) -> None:
    statement = build_upsert(sql.engine.dialect.name, "UP-1", "First", 100, 5)
    assert UPSERT_KEYWORD[sql.key] in str(statement.compile(dialect=sql.engine.dialect))

    upsert_product(db, "UP-1", "First", 100, 5)  # inserts
    upsert_product(db, "UP-1", "Second", 150, 7)  # updates the same row

    rows = db.execute(sa.text("SELECT name, price_cents, stock, version FROM products WHERE sku = 'UP-1'")).all()
    assert [tuple(row) for row in rows] == [("Second", 150, 7, 2)]


def test_for_update_rendering(sql: SqlTarget) -> None:
    """SQLAlchemy drops `with_for_update()` on SQL Server and SQLite without a warning."""
    dialect = sql.engine.dialect
    naive = str(sa.select(Product).with_for_update().compile(dialect=dialect))
    ours = str(select_product_for_update("X").compile(dialect=dialect))

    if sql.key in ("postgres", "mysql"):
        assert "FOR UPDATE" in naive
        assert "FOR UPDATE" in ours
    elif sql.key == "mssql":
        # The trap: no lock at all, and no warning.
        assert "FOR UPDATE" not in naive
        assert "UPDLOCK" not in naive
        assert "WITH (UPDLOCK, ROWLOCK)" in ours  # the fix in repository.py
    else:
        # SQLite: nothing to lock at row level; nothing rendered either way.
        assert "FOR UPDATE" not in naive
        assert "FOR UPDATE" not in ours


# --- Type and constraint enforcement ---------------------------------------------------

# Inserting the text 'abc' into the INTEGER price column.
TEXT_IN_INTEGER_COLUMN = {
    "postgres": "rejected",
    "mysql": "rejected",  # STRICT_TRANS_TABLES is on by default in MySQL 8
    "mssql": "rejected",
    # SQLite's "type affinity": a column type is a preference, not a rule (unless the
    # table is declared STRICT). The CHECK (price_cents > 0) passes too, because in
    # SQLite any text sorts after any number.
    "sqlite": "stored",
}


def test_text_in_an_integer_column(sql: SqlTarget, db: sa.Connection) -> None:
    statement = sa.text("INSERT INTO products (sku, name, price_cents, stock) VALUES ('T-1', 'Typed', 'abc', 1)")
    try:
        with db.begin_nested():
            db.execute(statement)
        outcome = "stored"
    except DBAPIError:
        outcome = "rejected"
    assert outcome == TEXT_IN_INTEGER_COLUMN[sql.key]


def test_sqlite_foreign_keys_are_off_unless_enabled(sql: SqlTarget) -> None:
    """Why database.py runs PRAGMA foreign_keys = ON on every SQLite connection."""
    if sql.key != "sqlite":
        pytest.skip("SQLite-only: the other engines always enforce foreign keys")

    path = sql.engine.url.database
    assert path is not None
    orphan = "INSERT INTO orders (product_id, quantity, customer_email) VALUES (999999, 1, 'a@example.com')"
    conn = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute(orphan)  # accepted: foreign keys are off by default
        conn.execute("ROLLBACK")

        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(orphan)
        conn.execute("ROLLBACK")
    finally:
        conn.close()
