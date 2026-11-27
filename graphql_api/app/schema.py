"""The GraphQL schema: types, resolvers, and the limits that protect the server.

Run `uv run python -m graphql_api.app.schema > graphql_api/schema.graphql` to refresh
the committed SDL after an intended schema change.
"""

import base64
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import strawberry
from graphql import GraphQLError
from sqlalchemy import select
from sqlalchemy.orm import Session
from strawberry import Info
from strawberry.dataloader import DataLoader
from strawberry.extensions import MaxAliasesLimiter, MaxTokensLimiter, QueryDepthLimiter
from strawberry.fastapi import BaseContext

from graphql_api.app.auth import IsAuthenticated, IsOwnerOrAdmin, User
from graphql_api.app.db import ContactRow, MessageRow

MAX_PAGE_SIZE = 50
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Context(BaseContext):
    session: Session
    user: User | None
    use_dataloader: bool
    messages_loader: DataLoader[int, list["Message"]] = field(init=False)

    def __post_init__(self) -> None:
        super().__init__()
        # A new loader per request: batching (and caching) never crosses users.
        self.messages_loader = DataLoader(load_fn=self._load_messages)

    async def _load_messages(self, contact_ids: list[int]) -> Sequence[list["Message"]]:
        """One query for the messages of every contact in the batch."""
        rows = self.session.scalars(
            select(MessageRow).where(MessageRow.contact_id.in_(contact_ids)).order_by(MessageRow.id)
        )
        by_contact: dict[int, list[Message]] = defaultdict(list)
        for row in rows:
            by_contact[row.contact_id].append(Message.from_row(row))
        return [by_contact[contact_id] for contact_id in contact_ids]


@strawberry.type
class Message:
    id: strawberry.ID
    body: str
    contact_id: strawberry.Private[int]

    @staticmethod
    def from_row(row: MessageRow) -> "Message":
        return Message(id=strawberry.ID(str(row.id)), body=row.body, contact_id=row.contact_id)

    @strawberry.field
    def contact(self, info: Info[Context, None]) -> "Contact":
        # The back-reference makes the schema cyclic (contact -> messages -> contact ...),
        # which is exactly why the depth limit below exists.
        row = info.context.session.get_one(ContactRow, self.contact_id)
        return Contact.from_row(row)


@strawberry.type
class Contact:
    id: strawberry.ID
    name: str
    owner: str
    stored_email: strawberry.Private[str]

    @staticmethod
    def from_row(row: ContactRow) -> "Contact":
        return Contact(id=strawberry.ID(str(row.id)), name=row.name, owner=row.owner, stored_email=row.email)

    @strawberry.field(permission_classes=[IsOwnerOrAdmin])
    def email(self) -> str | None:
        return self.stored_email

    @strawberry.field
    async def messages(self, info: Info[Context, None]) -> list[Message]:
        if info.context.use_dataloader:
            # Collected across all contacts in the response, then loaded in one query.
            return await info.context.messages_loader.load(int(self.id))
        # The naive version: one query per contact (the N+1 problem). Kept so the
        # N+1 test can show that its query counter catches it.
        rows = info.context.session.scalars(
            select(MessageRow).where(MessageRow.contact_id == int(self.id)).order_by(MessageRow.id)
        )
        return [Message.from_row(row) for row in rows]


@strawberry.type
class PageInfo:
    has_next_page: bool
    end_cursor: str | None


@strawberry.type
class ContactEdge:
    cursor: str
    node: Contact


@strawberry.type
class ContactConnection:
    edges: list[ContactEdge]
    page_info: PageInfo


def encode_cursor(contact_id: int) -> str:
    # Opaque to clients on purpose: they must not build cursors or rely on their format.
    return base64.urlsafe_b64encode(f"contact:{contact_id}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    try:
        kind, _, raw_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition(":")
        if kind != "contact":
            raise ValueError(kind)
        return int(raw_id)
    except ValueError as error:
        raise GraphQLError("Invalid cursor", extensions={"code": "BAD_USER_INPUT"}) from error


def bad_input(message: str) -> GraphQLError:
    return GraphQLError(message, extensions={"code": "BAD_USER_INPUT"})


@strawberry.type
class Query:
    @strawberry.field(permission_classes=[IsAuthenticated])
    def contacts(self, info: Info[Context, None], first: int = 10, after: str | None = None) -> ContactConnection:
        """The caller's contacts (every contact, for an admin), oldest first."""
        if not 1 <= first <= MAX_PAGE_SIZE:
            # Bounding page size is the simplest complexity limit: no "first: 1000000".
            raise bad_input(f"first must be between 1 and {MAX_PAGE_SIZE}")
        user: User = info.context.user  # type: ignore[assignment]  # IsAuthenticated ran
        query = select(ContactRow).order_by(ContactRow.id).limit(first + 1)
        if not user.is_admin:
            query = query.where(ContactRow.owner == user.name)
        if after is not None:
            query = query.where(ContactRow.id > decode_cursor(after))

        rows = list(info.context.session.scalars(query))
        page = rows[:first]  # we fetched one extra row only to learn whether there's a next page
        edges = [ContactEdge(cursor=encode_cursor(row.id), node=Contact.from_row(row)) for row in page]
        return ContactConnection(
            edges=edges,
            page_info=PageInfo(has_next_page=len(rows) > first, end_cursor=edges[-1].cursor if edges else None),
        )

    @strawberry.field(permission_classes=[IsAuthenticated])
    def contact(self, info: Info[Context, None], id: strawberry.ID) -> Contact | None:
        """Any contact by id. Signed-in users see names; emails are owner-only."""
        row = info.context.session.get(ContactRow, int(id))
        return Contact.from_row(row) if row else None


@strawberry.input
class CreateContactInput:
    name: str
    email: str


@strawberry.type
class Mutation:
    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def create_contact(self, info: Info[Context, None], input: CreateContactInput) -> Contact:
        if not EMAIL_PATTERN.match(input.email):
            raise bad_input("email is not a valid address")
        user: User = info.context.user  # type: ignore[assignment]
        row = ContactRow(owner=user.name, name=input.name, email=input.email)
        info.context.session.add(row)
        info.context.session.commit()
        return Contact.from_row(row)

    @strawberry.mutation(permission_classes=[IsAuthenticated])
    def send_message(self, info: Info[Context, None], contact_id: strawberry.ID, body: str) -> Message:
        user: User = info.context.user  # type: ignore[assignment]
        contact = info.context.session.get(ContactRow, int(contact_id))
        if contact is None or (contact.owner != user.name and not user.is_admin):
            # Same answer for "missing" and "not yours": don't confirm that an id exists.
            raise GraphQLError("Contact not found", extensions={"code": "NOT_FOUND"})
        if not body.strip():
            raise bad_input("body must not be empty")
        row = MessageRow(contact_id=contact.id, body=body)
        info.context.session.add(row)
        info.context.session.commit()
        return Message.from_row(row)


MAX_DEPTH = 6
MAX_ALIASES = 15
MAX_TOKENS = 2000

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        # Reject abusive queries before running any resolver:
        lambda: QueryDepthLimiter(max_depth=MAX_DEPTH),  # deep nesting through the cycle above
        lambda: MaxAliasesLimiter(max_alias_count=MAX_ALIASES),  # one field asked for 1000 times
        lambda: MaxTokensLimiter(max_token_count=MAX_TOKENS),  # huge documents in general
    ],
)

if __name__ == "__main__":
    print(schema.as_str())
