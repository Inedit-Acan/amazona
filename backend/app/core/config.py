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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://amazona:amazona@localhost:5432/amazona"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # Explicit opt-in, deliberately separate from is_supabase_configured:
    # merely having Supabase credentials in .env (to reach its Postgres or
    # its REST API) must never silently start requiring auth on every
    # mutating endpoint. Only set REQUIRE_AUTH=true once you actually want
    # that enforced.
    require_auth: bool = False

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
