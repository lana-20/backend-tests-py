"""Transactions: rollback, the lost-update problem, and two ways to prevent it.

Concurrency is simulated deterministically: two connections (two "users") take turns
in one thread, in a fixed order. Where the second user would block on a lock, it uses
NOWAIT instead, so the test gets an immediate error rather than a timing-dependent wait.
"""

import sqlite3

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from sql_engines.app.models import Order, Product
from sql_engines.app.models import products_table as products
from sql_engines.app.repository import select_product_for_update
from sql_engines.tests.conftest import SqlTarget


def read_stock(conn: sa.Connection, sku: str) -> int:
    return int(conn.execute(sa.select(products.c.stock).where(products.c.sku == sku)).scalar_one())


def write_stock(conn: sa.Connection, sku: str, stock: int) -> None:
    conn.execute(sa.update(products).where(products.c.sku == sku).values(stock=stock))


def test_rollback_undoes_every_statement(session: Session, db: sa.Connection) -> None:
    product = Product(sku="RB-1", name="Rollback", price_cents=100, stock=5)
    session.add(product)
    session.flush()

    nested = session.begin_nested()
    product.stock = 4
    session.add(Order(product_id=product.id, quantity=1, customer_email="a@example.com"))
    session.flush()
    nested.rollback()

    assert db.execute(sa.text("SELECT stock FROM products WHERE sku = 'RB-1'")).scalar_one() == 5
    assert db.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar_one() == 0


# What happens when two users read the same stock level, each subtracts one, and each
# writes back its result, with no locking. Ten minus two orders should be 8.
LOST_UPDATE_OUTCOME = {
    # Plain READ COMMITTED: both reads see 10, both write 9. One sale vanishes.
    "postgres": "lost update",
    # REPEATABLE READ (MySQL's default) doesn't help: B's UPDATE writes an absolute
    # value computed from its snapshot.
    "mysql": "lost update",
    # Locking READ COMMITTED releases the shared lock right after each read.
    "mssql": "lost update",
    # SQLite locks the whole file. A's commit needs an exclusive lock while B still
    # holds its read lock, so A fails ("database is locked") instead of losing data.
    "sqlite": "first writer blocked",
}


def test_lost_update_without_locking(sql: SqlTarget, committed_sku: str) -> None:
    with sql.engine.connect() as a, sql.engine.connect() as b:
        a.begin()
        b.begin()
        a_stock = read_stock(a, committed_sku)
        b_stock = read_stock(b, committed_sku)
        assert a_stock == b_stock == 10

        try:
            write_stock(a, committed_sku, a_stock - 1)
            a.commit()
            write_stock(b, committed_sku, b_stock - 1)
            b.commit()
            final = read_stock(a, committed_sku)
            outcome = "lost update" if final == 9 else f"final stock {final}"
        except OperationalError:
            a.rollback()
            b.rollback()
            outcome = "first writer blocked"

    assert outcome == LOST_UPDATE_OUTCOME[sql.key]


def test_select_for_update_makes_the_second_user_wait(sql: SqlTarget, committed_sku: str) -> None:
    """The fix the API uses: lock the row before reading the value you will change."""
    if sql.key == "sqlite":
        pytest.skip(
            "SQLite has no row-level locks and SQLAlchemy drops FOR UPDATE there; "
            "see test_sqlite_locks_the_whole_database instead"
        )

    with Session(sql.engine) as a, Session(sql.engine) as b:
        product_a = a.scalars(select_product_for_update(committed_sku)).one()

        # B asks for the same lock without waiting, and is refused at once. In real use
        # B would simply wait for A's commit; NOWAIT makes that observable without timing.
        with pytest.raises(OperationalError):
            b.scalars(select_product_for_update(committed_sku, nowait=True)).one()
        b.rollback()

        product_a.stock -= 1
        a.commit()

        # A's lock is gone. B now reads A's result, not the stale 10.
        product_b = b.scalars(select_product_for_update(committed_sku, nowait=True)).one()
        assert product_b.stock == 9
        product_b.stock -= 1
        b.commit()

    with sql.engine.connect() as conn:
        assert read_stock(conn, committed_sku) == 8


def test_sqlite_locks_the_whole_database(sql: SqlTarget, committed_sku: str) -> None:
    """SQLite's answer to FOR UPDATE: BEGIN IMMEDIATE takes the database's write lock."""
    if sql.key != "sqlite":
        pytest.skip("SQLite-only: the other engines lock rows; see the FOR UPDATE test")

    # Raw sqlite3 connections, because this is SQLite-specific behavior.
    path = sql.engine.url.database
    assert path is not None
    a = sqlite3.connect(path, timeout=0, isolation_level=None)
    b = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        a.execute("BEGIN IMMEDIATE")  # take the database's single write lock up front
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            b.execute("BEGIN IMMEDIATE")
        a.execute("ROLLBACK")
        b.execute("BEGIN IMMEDIATE")  # free again once A is done
        b.execute("ROLLBACK")
    finally:
        a.close()
        b.close()


def test_optimistic_locking_rejects_a_stale_write(sql: SqlTarget, committed_sku: str) -> None:
    """No locks held while a user "thinks": a version check at write time instead.

    This is the pattern for web apps, where the read and the write are separate HTTP
    requests (and often an ETag / If-Match pair on the API).
    """
    with (
        Session(sql.engine, expire_on_commit=False) as a,
        Session(sql.engine, expire_on_commit=False) as b,
    ):
        # Both users load version 1, each in its own short transaction.
        product_a = a.scalars(sa.select(Product).where(Product.sku == committed_sku)).one()
        a.commit()
        product_b = b.scalars(sa.select(Product).where(Product.sku == committed_sku)).one()
        b.commit()
        assert product_a.version == product_b.version == 1

        product_a.stock = 9
        a.commit()  # UPDATE ... WHERE id = ? AND version = 1  -> 1 row, version becomes 2

        product_b.stock = 9
        with pytest.raises(StaleDataError):
            b.commit()  # UPDATE ... WHERE id = ? AND version = 1  -> 0 rows

    with sql.engine.connect() as conn:
        row = conn.execute(sa.select(products.c.stock, products.c.version).where(products.c.sku == committed_sku)).one()
    assert tuple(row) == (9, 2)
