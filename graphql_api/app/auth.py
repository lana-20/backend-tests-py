"""Who is calling, and what they may see.

Tokens are a fixed lookup table to keep the demo small. A real API would verify a signed
JWT here; everything after this lookup (the permission classes) would stay the same.
"""

from dataclasses import dataclass
from typing import Any

from strawberry import Info
from strawberry.permission import BasePermission


@dataclass(frozen=True)
class User:
    name: str
    is_admin: bool = False


TOKENS = {
    "alice-token": User("alice"),
    "bob-token": User("bob"),
    "admin-token": User("admin", is_admin=True),
}


def user_from_header(authorization: str | None) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return TOKENS.get(authorization.removeprefix("Bearer "))


class IsAuthenticated(BasePermission):
    message = "You must be signed in"
    # GraphQL has no status codes per field; clients branch on extensions.code instead.
    error_extensions = {"code": "UNAUTHENTICATED"}

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        return info.context.user is not None


class IsOwnerOrAdmin(BasePermission):
    """Field-level rule: a contact's email is visible to its owner and to admins only."""

    message = "Only the contact's owner can see this field"
    error_extensions = {"code": "FORBIDDEN"}

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        user: User | None = info.context.user
        return user is not None and (user.is_admin or source.owner == user.name)
