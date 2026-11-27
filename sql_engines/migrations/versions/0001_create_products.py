"""Create the products table.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("name", sa.Unicode(100), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.CheckConstraint("price_cents > 0", name="ck_products_price_positive"),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock_not_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )


def downgrade() -> None:
    op.drop_table("products")
