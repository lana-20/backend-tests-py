"""Add optimistic locking to products, and create the orders table.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode: on SQLite this rebuilds the table; elsewhere it's a plain ALTER TABLE.
    # The server default lets existing rows get a value for the new NOT NULL column.
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_orders_product_id"),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
    )


def downgrade() -> None:
    op.drop_table("orders")
    with op.batch_alter_table("products") as batch:
        # SQL Server attached an auto-named DEFAULT constraint to the column; it must be
        # dropped first, or DROP COLUMN fails. Other engines ignore this option.
        batch.drop_column("version", mssql_drop_default=True)
