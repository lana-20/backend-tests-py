"""A one-endpoint HTTP API that places orders. Tests call it, then check the rows."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sql_engines.app.models import Order
from sql_engines.app.repository import select_product_for_update


def get_session() -> Iterator[Session]:
    """Where the app gets its database session.

    A deployed app would open a session from a configured engine here. The tests replace
    this dependency with a session inside a transaction that is rolled back afterwards.
    """
    raise NotImplementedError("Override get_session via app.dependency_overrides")


class OrderIn(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    customer_email: str


class OrderOut(BaseModel):
    id: int
    sku: str
    quantity: int
    remaining_stock: int


app = FastAPI(title="shop")


@app.post("/orders", status_code=201)
def place_order(body: OrderIn, session: Annotated[Session, Depends(get_session)]) -> OrderOut:
    # Lock the product row first, so two concurrent orders can't both read the same
    # stock level and both succeed (the lost-update problem).
    product = session.scalars(select_product_for_update(body.sku)).one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Unknown SKU")
    if product.stock < body.quantity:
        session.rollback()  # release the row lock
        raise HTTPException(status_code=409, detail="Not enough stock")

    product.stock -= body.quantity
    order = Order(product_id=product.id, quantity=body.quantity, customer_email=body.customer_email)
    session.add(order)
    session.commit()
    return OrderOut(id=order.id, sku=product.sku, quantity=order.quantity, remaining_stock=product.stock)
