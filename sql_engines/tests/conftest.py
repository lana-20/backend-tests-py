"""Fixtures for the SQL suite. Every test runs once per engine.

`sql` is parametrized by engine, and each param carries a marker, so
`pytest sql_engines -m postgres` runs just the PostgreSQL leg.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import allure
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from sql_engines.app.database import upgrade
from sql_engines.app.models import Order, Product
from sql_engines.app.models import products_table as products
from sql_engines.tests.servers import ENGINES, DatabaseServer, start_server


@dataclass
class SqlTarget:
    key: str  # "postgres", "mysql", "mssql" or "sqlite"
    label: str
    server: DatabaseServer
    engine: sa.Engine  # the "app" database, migrated to the latest revision


@pytest.fixture(
    scope="session",
    params=[pytest.param(key, marks=getattr(pytest.mark, key)) for key in ENGINES],
)
def sql(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[SqlTarget]:
    key: str = request.param
    tmp_dir: Path = tmp_path_factory.mktemp(key)
    with start_server(key, tmp_dir) as server:
        engine = server.create_database("app")
        # The schema comes from the migrations, as in production, not from create_all().
        upgrade(engine)
        yield SqlTarget(key, server.info.label, server, engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def _allure_labels(sql: SqlTarget) -> None:
    allure.dynamic.parent_suite("SQL")
    allure.dynamic.suite(sql.label)
    allure.dynamic.tag(sql.key)


@pytest.fixture
def db(sql: SqlTarget) -> Iterator[sa.Connection]:
    """A connection inside a transaction that is always rolled back.

    Whatever a test writes disappears afterwards, so tests don't see each other's rows
    and can run in any order. Code under test may call commit(): sessions bound with
    join_transaction_mode="create_savepoint" (below) turn that into a SAVEPOINT release.
    """
    with sql.engine.connect() as conn:
        transaction = conn.begin()
        try:
            yield conn
        finally:
            transaction.rollback()


@pytest.fixture
def session(db: sa.Connection) -> Iterator[Session]:
    """An ORM session that joins the rolled-back transaction of `db`."""
    with Session(bind=db, join_transaction_mode="create_savepoint") as orm_session:
        yield orm_session


@pytest.fixture
def committed_sku(sql: SqlTarget) -> Iterator[str]:
    """A committed product row (stock 10), for tests that use two connections.

    The rolled-back `db` fixture can't serve those tests: its rows are invisible to
    other connections. A unique SKU keeps this row apart from every other test's.
    """
    sku = f"TX-{uuid4().hex[:8]}"
    with sql.engine.begin() as conn:
        conn.execute(sa.insert(products).values(sku=sku, name="Lock test", price_cents=100, stock=10))
    yield sku
    with sql.engine.begin() as conn:
        conn.execute(sa.delete(products).where(products.c.sku == sku))


# Deterministic sample data: (sku, name, price_cents, stock).
PRODUCTS = [
    ("SKU-001", "Notebook", 450, 100),
    ("SKU-002", "Pen", 120, 500),
    ("SKU-003", "Backpack", 3999, 20),
    ("SKU-004", "Stapler", 899, 0),
]
# (sku, quantity, customer_email)
ORDERS = [
    ("SKU-001", 3, "ana@example.com"),
    ("SKU-002", 10, "ana@example.com"),
    ("SKU-003", 1, "ben@example.com"),
    ("SKU-001", 2, "ben@example.com"),
    ("SKU-002", 5, "cy@example.com"),
]


@pytest.fixture
def seeded(session: Session) -> Session:
    """`session`, plus the sample products and orders above."""
    by_sku = {}
    for sku, name, price, stock in PRODUCTS:
        by_sku[sku] = Product(sku=sku, name=name, price_cents=price, stock=stock)
    session.add_all(by_sku.values())
    session.flush()
    session.add_all(Order(product_id=by_sku[sku].id, quantity=qty, customer_email=email) for sku, qty, email in ORDERS)
    # Releases the session's SAVEPOINT: the rows stay in the outer (rolled-back)
    # transaction, and a later session.rollback() in the code under test can't undo them.
    session.commit()
    return session
