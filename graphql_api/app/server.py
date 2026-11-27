"""The FastAPI app that serves the schema at /graphql."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, Header
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from strawberry.fastapi import GraphQLRouter

from graphql_api.app.auth import user_from_header
from graphql_api.app.schema import Context, schema


def create_app(engine: Engine, *, use_dataloader: bool = True) -> FastAPI:
    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def get_context(
        session: Annotated[Session, Depends(get_session)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Context:
        return Context(session=session, user=user_from_header(authorization), use_dataloader=use_dataloader)

    app = FastAPI(title="contacts-graphql")
    app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")
    return app
