"""The database itself rejects bad rows, whatever the application code does.

Each insert runs in a SAVEPOINT (`begin_nested`), so a rejected statement is undone
without aborting the test's outer transaction (PostgreSQL would otherwise refuse every
later statement in the transaction).
"""

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from sql_engines.app.models import orders_table as orders
from sql_engines.app.models import products_table as products
from sql_engines.tests.conftest import SqlTarget


def insert_product(db: sa.Connection, **overrides: Any) -> int:
    values = {"sku": "SKU-1", "name": "Widget", "price_cents": 100, "stock": 1} | overrides
    key = db.execute(sa.insert(products).values(**values)).inserted_primary_key
    assert key is not None
    return int(key[0])


def rejected(db: sa.Connection, statement: sa.Executable) -> DBAPIError:
    """Run `statement` in a savepoint and return the error the database raised."""
    with pytest.raises(DBAPIError) as caught, db.begin_nested():
        db.execute(statement)
    return caught.value


def test_not_null(db: sa.Connection) -> None:
    error = rejected(db, sa.insert(products).values(sku="SKU-1", name=None, price_cents=100, stock=1))
    assert isinstance(error, IntegrityError)


def test_unique_sku(db: sa.Connection) -> None:
    insert_product(db, sku="SKU-1")
    error = rejected(db, sa.insert(products).values(sku="SKU-1", name="Copy", price_cents=100, stock=1))
    assert isinstance(error, IntegrityError)


def test_foreign_key(db: sa.Connection) -> None:
    error = rejected(db, sa.insert(orders).values(product_id=999_999, quantity=1, customer_email="a@example.com"))
    assert isinstance(error, IntegrityError)


@pytest.mark.parametrize(
    ("column", "bad_value", "constraint"),
    [
        ("price_cents", 0, "ck_products_price_positive"),
        ("stock", -1, "ck_products_stock_not_negative"),
    ],
)
def test_check_constraints(sql: SqlTarget, db: sa.Connection, column: str, bad_value: int, constraint: str) -> None:
    values = {"sku": "SKU-1", "name": "Widget", "price_cents": 100, "stock": 1, column: bad_value}
    error = rejected(db, sa.insert(products).values(**values))

    # Every engine names the constraint that fired, which makes the failure actionable.
    assert constraint in str(error)
    # All four engines enforce CHECK (MySQL only since 8.0.16; older versions parsed it
    # and silently ignored it). But the error *class* differs: PyMySQL has no mapping for
    # MySQL error 3819 and raises OperationalError, not IntegrityError. Code that catches
    # IntegrityError to report "bad input" would miss CHECK failures on MySQL.
    expected = OperationalError if sql.key == "mysql" else IntegrityError
    assert type(error) is expected


def test_check_on_order_quantity(db: sa.Connection) -> None:
    product_id = insert_product(db)
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(sa.insert(orders).values(product_id=product_id, quantity=0, customer_email="a@example.com"))
