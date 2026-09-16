from sqlalchemy.orm import Session

from app.db.models.role import Role
from app.db.models.user import User


class RoleService:
    """Resolves a user's role from the database, so PermissionEngine checks
    are backed by real identity instead of a free-text actor_role string.
    A user with no role assigned (or that doesn't exist) resolves to None,
    which PermissionEngine.check() treats as denied by default — never as
    an implicit "allowed"."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def role_for(self, user_id: str) -> str | None:
        user = self._db.get(User, user_id)
        if user is None or user.role_id is None:
            return None
        role = self._db.get(Role, user.role_id)
        return role.name if role is not None else None
