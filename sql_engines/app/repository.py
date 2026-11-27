"""Queries that differ between engines, kept in one place so the differences are visible."""

from dataclasses import dataclass

from sqlalchemy import Connection, Insert, Select, TextClause, bindparam, func, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from sql_engines.app.models import Order, Product
from sql_engines.app.models import products_table as products


def select_product_for_update(sku: str, *, nowait: bool = False) -> Select[Product]:
    """SELECT one product and lock its row until the transaction ends.

    - PostgreSQL and MySQL: `... FOR UPDATE [NOWAIT]`.
    - SQL Server has no FOR UPDATE on plain SELECTs, and SQLAlchemy silently drops
      `with_for_update()` for it. Without the table hint below, this would compile to a
      plain SELECT that locks nothing. The hint is the SQL Server way to say the same.
    - SQLite has no row locks at all (it locks the whole database file), and SQLAlchemy
      drops FOR UPDATE there too. See the SQLite test in test_transactions.py.
    """
    hint = "WITH (UPDLOCK, ROWLOCK, NOWAIT)" if nowait else "WITH (UPDLOCK, ROWLOCK)"
    return (
        select(Product)
        .where(Product.sku == sku)
        .with_for_update(nowait=nowait)
        .with_hint(Product, hint, dialect_name="mssql")
    )


def build_upsert(dialect_name: str, sku: str, name: str, price_cents: int, stock: int) -> Insert | TextClause:
    """Insert a product, or update its name, price and stock if the SKU exists.

    Every engine spells "upsert" differently. Each branch also bumps `version`, because
    Core statements bypass the ORM's optimistic-locking bookkeeping.
    """
    values = {"sku": sku, "name": name, "price_cents": price_cents, "stock": stock}
    if dialect_name == "postgresql":
        pg = postgres_insert(products).values(**values)
        return pg.on_conflict_do_update(
            index_elements=["sku"],
            set_={
                "name": pg.excluded.name,
                "price_cents": pg.excluded.price_cents,
                "stock": pg.excluded.stock,
                "version": products.c.version + 1,
            },
        )
    if dialect_name == "sqlite":
        lite = sqlite_insert(products).values(**values)
        return lite.on_conflict_do_update(
            index_elements=["sku"],
            set_={
                "name": lite.excluded.name,
                "price_cents": lite.excluded.price_cents,
                "stock": lite.excluded.stock,
                "version": products.c.version + 1,
            },
        )
    if dialect_name == "mysql":
        my = mysql_insert(products).values(**values)
        # MySQL has no conflict target: ON DUPLICATE KEY fires for ANY unique key.
        return my.on_duplicate_key_update(
            name=my.inserted.name,
            price_cents=my.inserted.price_cents,
            stock=my.inserted.stock,
            version=products.c.version + 1,
        )
    if dialect_name == "mssql":
        # SQL Server has no INSERT ... ON CONFLICT; MERGE is the standard tool. HOLDLOCK
        # keeps two concurrent MERGEs from both deciding "not matched" and both inserting.
        return text(
            """
            MERGE products WITH (HOLDLOCK) AS target
            USING (SELECT :sku AS sku, :name AS name, :price_cents AS price_cents,
                          :stock AS stock) AS source
               ON target.sku = source.sku
            WHEN MATCHED THEN
                UPDATE SET name = source.name, price_cents = source.price_cents,
                           stock = source.stock, version = target.version + 1
            WHEN NOT MATCHED THEN
                INSERT (sku, name, price_cents, stock)
                VALUES (source.sku, source.name, source.price_cents, source.stock);
            """
        ).bindparams(
            bindparam("sku", sku),
            bindparam("name", name),
            bindparam("price_cents", price_cents),
            bindparam("stock", stock),
        )
    raise ValueError(f"No upsert for dialect {dialect_name!r}")


def upsert_product(conn: Connection, sku: str, name: str, price_cents: int, stock: int) -> None:
    conn.execute(build_upsert(conn.dialect.name, sku, name, price_cents, stock))


@dataclass(frozen=True)
class ProductSales:
    sku: str
    units_sold: int
    revenue_cents: int


def sales_by_product(session: Session) -> list[ProductSales]:
    """Units and revenue per product that has orders, best seller (by revenue) first."""
    revenue = func.sum(Order.quantity * Product.price_cents)
    stmt = (
        select(Product.sku, func.sum(Order.quantity), revenue)
        .join(Order, Order.product_id == Product.id)
        .group_by(Product.sku)
        .order_by(revenue.desc(), Product.sku)
    )
    return [ProductSales(sku, int(units), int(cents)) for sku, units, cents in session.execute(stmt)]


def cheapest_products(limit: int) -> Select[str]:
    """`.limit()` compiles to LIMIT on most engines and to TOP on SQL Server."""
    return select(Product.sku).order_by(Product.price_cents, Product.sku).limit(limit)
