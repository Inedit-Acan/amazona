from dataclasses import dataclass
from enum import StrEnum


class RoleName(StrEnum):
    """The roles of the plan maestro §P0.3. Stored in the `roles` table by name,
    seeded by the Milestone 29 migration."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"
    #: Internal identity for workers and background processes. Never issued to
    #: a human and never obtainable from a Supabase session.
    SYSTEM = "SYSTEM"


class ActorSource(StrEnum):
    """Where an actor's identity came from. Audit rows keep it so that a
    historical entry says whether the name in `actor` was verified or merely
    claimed by the caller."""

    #: Verified against the signature of an access token.
    TOKEN = "token"
    #: Sent by the client and taken at face value. Only outside staging and
    #: production (Settings.allows_declared_actor).
    DECLARED = "declared"
    #: Local management command.
    CLI = "cli"
    #: The backend acting on its own behalf.
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    """Who is performing an action, and how much that identity is worth."""

    subject: str
    email: str | None = None
    role: RoleName | None = None
    source: ActorSource = ActorSource.DECLARED

    @property
    def is_verified(self) -> bool:
        return self.source is ActorSource.TOKEN

    @property
    def audit_name(self) -> str:
        """What goes in `audit_log.actor`: the email when it is known, because
        it is what a human reading the trail recognises, and the subject
        otherwise."""
        return self.email or self.subject
