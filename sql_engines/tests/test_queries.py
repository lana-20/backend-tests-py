"""Query correctness: the ORM query agrees with hand-written SQL and with known numbers."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from sql_engines.app.repository import ProductSales, sales_by_product

# Worked out by hand from the sample data in conftest.py:
#   SKU-001 Notebook  450c x (3 + 2)  = 2250c
#   SKU-002 Pen       120c x (10 + 5) = 1800c
#   SKU-003 Backpack 3999c x 1        = 3999c
#   SKU-004 Stapler: no orders, so not listed
EXPECTED = [
    ProductSales("SKU-003", 1, 3999),
    ProductSales("SKU-001", 5, 2250),
    ProductSales("SKU-002", 15, 1800),
]

# The same question in plain SQL that runs unchanged on all four engines.
PLAIN_SQL = """
    SELECT p.sku, SUM(o.quantity) AS units, SUM(o.quantity * p.price_cents) AS revenue
    FROM products p
    JOIN orders o ON o.product_id = p.id
    GROUP BY p.sku
    ORDER BY revenue DESC, p.sku
"""


def test_sales_by_product_matches_known_values(seeded: Session) -> None:
    assert sales_by_product(seeded) == EXPECTED


def test_sales_by_product_matches_plain_sql(seeded: Session) -> None:
    rows = seeded.execute(sa.text(PLAIN_SQL)).all()
    from_sql = [ProductSales(sku, int(units), int(revenue)) for sku, units, revenue in rows]
    assert sales_by_product(seeded) == from_sql


def test_products_without_orders_are_left_out(seeded: Session) -> None:
    # An inner join: a product nobody ordered has no row to sum.
    assert "SKU-004" not in {line.sku for line in sales_by_product(seeded)}
