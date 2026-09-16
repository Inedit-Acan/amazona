from collections.abc import Callable
from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel

from app.core.errors import AmazonaError


class AuthError(AmazonaError):
    """Raised when a bearer token is missing, malformed, or fails verification."""


class AuthenticatedUser(BaseModel):
    sub: str
    email: str | None = None
    raw_claims: dict


def _jwks_signing_key(supabase_url: str, token: str) -> Any:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    client = PyJWKClient(jwks_url)
    return client.get_signing_key_from_jwt(token).key


class AuthService:
    """Verifies a Supabase Auth JWT.

    `get_signing_key` is injectable so tests can verify against a locally
    generated key pair instead of fetching Supabase's real JWKS endpoint
    over the network; production code leaves it unset and resolves the
    signing key from `supabase_url`'s JWKS.
    """

    def __init__(self, supabase_url: str = "", get_signing_key: Callable[[str], Any] | None = None) -> None:
        self._supabase_url = supabase_url
        self._get_signing_key = get_signing_key or (lambda token: _jwks_signing_key(self._supabase_url, token))

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            signing_key = self._get_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "ES256"],
                options={"verify_aud": False},
            )
        except Exception as exc:  # noqa: BLE001 - any failure is an auth failure, reported uniformly
            raise AuthError(f"invalid token: {exc}") from exc

        sub = claims.get("sub")
        if not sub:
            raise AuthError("token is missing the required 'sub' claim")

        return AuthenticatedUser(sub=sub, email=claims.get("email"), raw_claims=claims)
