"""Storage for the GraphQL API: contacts and their messages, in SQLite via SQLAlchemy.

SQLite in memory keeps this section free of containers: the point here is the GraphQL
layer, and the SQL section covers real database engines.
"""

from sqlalchemy import Engine, ForeignKey, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class ContactRow(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255))
    messages: Mapped[list["MessageRow"]] = relationship(back_populates="contact", order_by="MessageRow.id")


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    body: Mapped[str] = mapped_column(String(1000))
    contact: Mapped[ContactRow] = relationship(back_populates="messages")


def make_engine() -> Engine:
    # One shared in-memory database (StaticPool = one connection for everyone), usable
    # from the server's threads. Each test builds its own engine, so tests are isolated.
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


def seed(engine: Engine, contacts_per_owner: dict[str, int], messages_per_contact: int = 2) -> None:
    """Deterministic data: contacts are numbered in insertion order, owner by owner."""
    with Session(engine) as session:
        for owner, count in contacts_per_owner.items():
            for n in range(1, count + 1):
                contact = ContactRow(owner=owner, name=f"{owner.title()} contact {n}", email=f"{owner}.{n}@example.com")
                contact.messages = [
                    MessageRow(body=f"Message {m} to {contact.name}") for m in range(1, messages_per_contact + 1)
                ]
                session.add(contact)
        session.commit()
