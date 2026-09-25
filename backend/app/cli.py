"""Management commands run by a human on the machine that owns the database.

There is deliberately no HTTP endpoint that grants roles: the first OWNER has to
exist before anyone can authenticate as one, and an endpoint able to create that
first OWNER would be an endpoint able to escalate anybody (Milestone 29,
ADR 0007).

    AMAZONA_BOOTSTRAP=1 python -m app.cli grant-role --email you@example.com --role OWNER

Requires AMAZONA_BOOTSTRAP=1 in the environment so the command cannot be run by
accident, and writes an audit entry for every grant.
"""

import argparse
import os
import sys

from sqlalchemy.orm import Session

from app.auth.actor import ActorSource, RoleName
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_session_factory

BOOTSTRAP_ENV = "AMAZONA_BOOTSTRAP"


class BootstrapError(RuntimeError):
    """The command refused to run. Never a stack trace for the operator."""


def _require_bootstrap_flag() -> None:
    if os.environ.get(BOOTSTRAP_ENV) != "1":
        raise BootstrapError(
            f"refusing to change roles without {BOOTSTRAP_ENV}=1 in the environment"
        )


def grant_role(db: Session, *, email: str, role_name: str, force: bool = False) -> User:
    try:
        role_value = RoleName(role_name.upper())
    except ValueError as exc:
        known = ", ".join(r.value for r in RoleName)
        raise BootstrapError(f"unknown role {role_name!r}; known roles: {known}") from exc

    role = db.query(Role).filter_by(name=role_value.value).one_or_none()
    if role is None:
        raise BootstrapError(
            f"role {role_value} is missing from the database; run `alembic upgrade head` first"
        )

    if role_value is RoleName.OWNER and not force:
        existing_owner = (
            db.query(User).filter(User.role_id == role.id, User.email != email).first()
        )
        if existing_owner is not None:
            raise BootstrapError(
                f"{existing_owner.email} is already OWNER; pass --force to add another one"
            )

    user = db.query(User).filter_by(email=email).one_or_none()
    before = {"role": None} if user is None else {"role": role_name_of(db, user)}
    if user is None:
        user = User(email=email, role_id=role.id)
        db.add(user)
    else:
        user.role_id = role.id

    db.flush()
    db.add(
        AuditLog(
            actor=f"cli:{os.environ.get('USERNAME') or os.environ.get('USER') or 'unknown'}",
            actor_role=RoleName.OWNER,
            actor_source=ActorSource.CLI,
            action="user.grant_role",
            resource=f"user:{user.id}",
            before=before,
            after={"role": role_value.value, "email": email},
            correlation_id=new_correlation_id(),
        )
    )
    db.commit()
    db.refresh(user)
    return user


def role_name_of(db: Session, user: User) -> str | None:
    if user.role_id is None:
        return None
    role = db.get(Role, user.role_id)
    return role.name if role else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    grant = commands.add_parser("grant-role", help="give a person a role, creating the user if needed")
    grant.add_argument("--email", required=True)
    grant.add_argument("--role", required=True, help=", ".join(r.value for r in RoleName))
    grant.add_argument("--force", action="store_true", help="allow a second OWNER")

    commands.add_parser("list-users", help="show every user and its role")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = get_session_factory()()
    try:
        if args.command == "grant-role":
            _require_bootstrap_flag()
            user = grant_role(db, email=args.email, role_name=args.role, force=args.force)
            print(f"{user.email} is now {args.role.upper()}")
        elif args.command == "list-users":
            users = db.query(User).order_by(User.email).all()
            if not users:
                print("no users yet")
            for user in users:
                linked = "linked" if user.subject else "never signed in"
                print(f"{user.email:40} {role_name_of(db, user) or '(no role)':10} {linked}")
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
