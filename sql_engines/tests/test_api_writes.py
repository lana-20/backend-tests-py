"""Data integrity after an API call: the API writes, the test reads the rows back."""

from collections.abc import Iterator

import pytest
import requests
import sqlalchemy as sa
from sqlalchemy.orm import Session

from common.http_server import serve
from sql_engines.app.api import app, get_session


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def post(self, path: str, json: dict[str, object]) -> requests.Response:
        return requests.post(self.base_url + path, json=json, timeout=10)


@pytest.fixture
def client(seeded: Session) -> Iterator[Client]:
    # The API uses the test's session, so its commit() lands in a SAVEPOINT that the
    # `db` fixture rolls back at the end. Nothing leaks into the next test.
    app.dependency_overrides[get_session] = lambda: seeded
    with serve(app) as base_url:
        yield Client(base_url)
    app.dependency_overrides.clear()


def stock(db: sa.Connection, sku: str) -> int:
    return int(db.execute(sa.text("SELECT stock FROM products WHERE sku = :sku"), {"sku": sku}).scalar_one())


def order_count(db: sa.Connection) -> int:
    return int(db.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar_one())


def test_order_writes_the_order_and_decrements_stock(client: Client, db: sa.Connection) -> None:
    orders_before = order_count(db)

    response = client.post("/orders", json={"sku": "SKU-003", "quantity": 2, "customer_email": "dee@example.com"})

    assert response.status_code == 201
    body = response.json()
    assert body["remaining_stock"] == 18

    # Don't trust the response: read what is actually stored.
    row = db.execute(
        sa.text(
            "SELECT o.quantity, o.customer_email, p.sku FROM orders o "
            "JOIN products p ON p.id = o.product_id WHERE o.id = :id"
        ),
        {"id": body["id"]},
    ).one()
    assert tuple(row) == (2, "dee@example.com", "SKU-003")
    assert stock(db, "SKU-003") == 18
    assert order_count(db) == orders_before + 1
    # The ORM bumped the optimistic-locking version on the product it changed.
    assert db.execute(sa.text("SELECT version FROM products WHERE sku = 'SKU-003'")).scalar_one() == 2


def test_order_for_more_than_the_stock_changes_nothing(client: Client, db: sa.Connection) -> None:
    orders_before = order_count(db)

    response = client.post("/orders", json={"sku": "SKU-003", "quantity": 21, "customer_email": "dee@example.com"})

    assert response.status_code == 409
    assert stock(db, "SKU-003") == 20
    assert order_count(db) == orders_before


def test_order_for_an_unknown_sku_is_404(client: Client, db: sa.Connection) -> None:
    orders_before = order_count(db)
    response = client.post("/orders", json={"sku": "NOPE", "quantity": 1, "customer_email": "dee@example.com"})
    assert response.status_code == 404
    assert order_count(db) == orders_before


def test_invalid_quantity_is_rejected_before_the_database(client: Client, db: sa.Connection) -> None:
    orders_before = order_count(db)
    response = client.post("/orders", json={"sku": "SKU-001", "quantity": 0, "customer_email": "dee@example.com"})
    assert response.status_code == 422
    assert order_count(db) == orders_before
    assert stock(db, "SKU-001") == 100
