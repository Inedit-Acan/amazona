from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored to backend/.env regardless of the process's current working
# directory. A relative "env_file" is resolved against cwd, and
# pydantic-settings silently skips a missing .env instead of erroring —
# so invoking alembic/uvicorn/pytest from anywhere other than backend/
# (e.g. the repo root) used to silently fall back to the hardcoded
# localhost default below instead of failing loudly.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Environment(StrEnum):
    """Where this process is running. The distinction is what decides whether
    identity is enforced and whether simulated data may be used at all
    (Milestone 29, ADR 0007).

    - development: local work. Mocks allowed, identity optional.
    - test: automated suites. Controlled fixtures.
    - demo: demonstrations. Demo data allowed, but labelled as such.
    - staging: real integrations in sandbox. Identity enforced.
    - production: real operation. Identity enforced, no demo data for
      operational decisions.
    """

    DEVELOPMENT = "development"
    TEST = "test"
    DEMO = "demo"
    STAGING = "staging"
    PRODUCTION = "production"


#: Environments that run against real systems and therefore refuse anonymous
#: mutations and client-declared identity.
_ENFORCING = frozenset({Environment.STAGING, Environment.PRODUCTION})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://amazona:amazona@localhost:5432/amazona"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    #: `aud` claim Supabase puts in the access tokens it issues. Configurable
    #: because a self-hosted GoTrue can be told to use another one.
    jwt_audience: str = "authenticated"

    # Explicit opt-in for the non-enforcing environments, deliberately separate
    # from is_supabase_configured: merely having Supabase credentials in .env
    # (to reach its Postgres or its REST API) must never silently start
    # requiring auth on every mutating endpoint while developing. In staging and
    # production auth is enforced regardless of this flag — see enforces_auth.
    require_auth: bool = False

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def enforces_auth(self) -> bool:
        """Mutating endpoints demand a verified bearer token."""
        return self.environment in _ENFORCING or self.require_auth

    @property
    def enforces_rbac(self) -> bool:
        """The actor's role decides what it may do. Only the environments that
        touch real systems: in development an authenticated user is enough, so
        a local session without a seeded role keeps working as before."""
        return self.environment in _ENFORCING

    @property
    def allows_declared_actor(self) -> bool:
        """Whether an `actor` field in a request body may be trusted. Never in
        staging or production (plan maestro §P0.3)."""
        return self.environment not in _ENFORCING

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    def validate_for_startup(self) -> None:
        """Refuses to start a misconfigured enforcing environment. Failing loudly
        here is the whole point: a production deployment that silently accepts
        anonymous mutations is worse than one that does not boot."""
        if self.environment not in _ENFORCING:
            return

        problems: list[str] = []
        if not self.supabase_url:
            problems.append("SUPABASE_URL is required to verify access tokens")
        if not self.is_supabase_configured:
            problems.append("SUPABASE_ANON_KEY is required")
        if self.environment is Environment.PRODUCTION:
            local = [origin for origin in self.cors_origins if "localhost" in origin or "127.0.0.1" in origin]
            if local:
                problems.append(f"CORS_ORIGINS must not include local origins in production: {local}")

        if problems:
            raise RuntimeError(f"invalid configuration for {self.environment}: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
