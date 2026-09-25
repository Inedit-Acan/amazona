from sqlalchemy.orm import Session

from app.auth.actor import RoleName
from app.db.models.role import Role
from app.db.models.user import User


class RoleService:
    """Resolves a user's role from the database, so permission checks are
    backed by real identity instead of a free-text actor_role string.
    A user with no role assigned (or that doesn't exist) resolves to None,
    which every caller treats as denied by default — never as an implicit
    "allowed"."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def role_for(self, user_id: str) -> str | None:
        user = self._db.get(User, user_id)
        if user is None or user.role_id is None:
            return None
        role = self._db.get(Role, user.role_id)
        return role.name if role is not None else None

    def user_for_subject(self, subject: str, email: str | None = None) -> User | None:
        """Finds the local user behind an access token.

        Looks the token's `sub` up in `users.subject` first. On a first login
        the column is still empty, so a user registered by email — which is how
        the owner seeds people with `python -m app.cli grant-role` — is claimed
        by that subject once, and from then on the lookup is by subject only.
        Matching by email alone afterwards would let a re-registered account
        inherit someone else's role.
        """
        user = self._db.query(User).filter_by(subject=subject).one_or_none()
        if user is not None:
            return user

        if not email:
            return None

        unclaimed = self._db.query(User).filter_by(email=email, subject=None).one_or_none()
        if unclaimed is None:
            return None

        unclaimed.subject = subject
        self._db.add(unclaimed)
        self._db.commit()
        self._db.refresh(unclaimed)
        return unclaimed

    def role_for_subject(self, subject: str, email: str | None = None) -> RoleName | None:
        user = self.user_for_subject(subject, email)
        if user is None or user.role_id is None:
            return None
        role = self._db.get(Role, user.role_id)
        if role is None:
            return None
        try:
            return RoleName(role.name)
        except ValueError:
            # A role row whose name is not one of the seven known roles grants
            # nothing: an unrecognised name must never widen permissions.
            return None
