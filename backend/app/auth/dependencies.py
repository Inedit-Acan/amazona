from fastapi import Depends, HTTPException, Request

from app.auth.service import AuthError, AuthService
from app.core.config import Settings, get_settings


def get_auth_service(settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(supabase_url=settings.supabase_url)


async def get_current_actor(
    request: Request,
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> str | None:
    """Returns the authenticated actor's `sub`, or None when auth is not
    required (settings.require_auth is False — the Milestone 1 default,
    kept even when Supabase credentials happen to be configured for other
    reasons). Callers fall back to a body-supplied actor when this is None.
    """
    if not settings.require_auth:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        user = auth_service.verify(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return user.sub
