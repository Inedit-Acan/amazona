from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.actor import Actor, ActorSource, RoleName
from app.auth.service import AuthError, AuthService
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.permissions.policies import ApiAction, role_can
from app.permissions.roles import RoleService

#: Subject used for the anonymous local actor in the non-enforcing
#: environments. It is not a real identity and never reaches staging or
#: production, where `Settings.enforces_auth` is always true.
LOCAL_SUBJECT = "local-development"


def get_auth_service(settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(supabase_url=settings.supabase_url, audience=settings.jwt_audience)


def _verified_actor(request: Request, auth_service: AuthService, db: Session) -> Actor:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        user = auth_service.verify(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return Actor(
        subject=user.sub,
        email=user.email,
        role=RoleService(db).role_for_subject(user.sub, user.email),
        source=ActorSource.TOKEN,
    )


async def resolve_actor(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> Actor:
    """The identity behind a request.

    When the environment enforces auth there must be a valid bearer token, and
    the role comes from the database. Otherwise the caller gets an unverified
    local actor, so the owner's development setup keeps working without a
    Supabase session — exactly as it did before Milestone 29.
    """
    if settings.enforces_auth:
        return _verified_actor(request, auth_service, db)
    return Actor(subject=LOCAL_SUBJECT, email=None, role=None, source=ActorSource.DECLARED)


def authorize(action: ApiAction) -> Callable[[Actor, Settings], Actor]:
    """Dependency for a mutating route: 401 without a verified identity, 403
    when the role does not allow `action`.

    The role check only runs where RBAC is enforced (staging and production).
    In development an authenticated — or simply local — actor is enough, so
    seeding roles is a deployment step and not a prerequisite for working on
    the project.
    """

    def dependency(
        actor: Actor = Depends(resolve_actor),
        settings: Settings = Depends(get_settings),
    ) -> Actor:
        if settings.enforces_rbac and not role_can(actor.role, action):
            raise HTTPException(
                status_code=403,
                detail=f"role {actor.role or 'none'} is not allowed to perform {action}",
            )
        return actor

    return dependency


def actor_name(actor: Actor, declared: str | None, settings: Settings) -> str:
    """What to persist as the actor of an action.

    A verified identity always wins. A name sent in the request body is only
    honoured outside staging and production (plan maestro §P0.3: "no confiar en
    campos actor enviados por frontend para acciones protegidas").
    """
    if actor.is_verified:
        return actor.audit_name
    if declared and settings.allows_declared_actor:
        return declared
    return actor.audit_name


__all__ = [
    "LOCAL_SUBJECT",
    "Actor",
    "ActorSource",
    "RoleName",
    "actor_name",
    "authorize",
    "get_auth_service",
    "resolve_actor",
]
