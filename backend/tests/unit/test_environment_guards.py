"""Milestone 29: what each environment does and does not allow.

The point of these is that the difference between development and production is
not a habit but a property of Settings, checked here.
"""

import pytest

from app.core.config import Environment, Settings

CONFIGURED = {"supabase_url": "https://example.supabase.co", "supabase_anon_key": "anon-key"}


def settings_for(environment: Environment, **overrides) -> Settings:
    return Settings(_env_file=None, environment=environment, **overrides)


@pytest.mark.parametrize(
    "environment", [Environment.DEVELOPMENT, Environment.TEST, Environment.DEMO]
)
def test_local_environments_do_not_enforce_anything_by_default(environment: Environment):
    settings = settings_for(environment)

    assert settings.enforces_auth is False
    assert settings.enforces_rbac is False
    assert settings.allows_declared_actor is True


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_real_environments_always_enforce_identity(environment: Environment):
    settings = settings_for(environment, **CONFIGURED)

    assert settings.enforces_auth is True
    assert settings.enforces_rbac is True
    # An actor sent in a request body is never trusted here.
    assert settings.allows_declared_actor is False


def test_require_auth_still_works_as_a_local_opt_in():
    settings = settings_for(Environment.DEVELOPMENT, require_auth=True)

    assert settings.enforces_auth is True
    # …but a local session without a seeded role keeps working.
    assert settings.enforces_rbac is False


def test_production_refuses_to_start_without_supabase():
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        settings_for(Environment.PRODUCTION).validate_for_startup()


def test_production_refuses_to_start_with_a_local_cors_origin():
    settings = settings_for(
        Environment.PRODUCTION, cors_origins=["https://kova.example", "http://localhost:3000"], **CONFIGURED
    )

    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        settings.validate_for_startup()


def test_a_correctly_configured_production_starts():
    settings = settings_for(Environment.PRODUCTION, cors_origins=["https://kova.example"], **CONFIGURED)

    settings.validate_for_startup()


def test_development_never_fails_startup_validation():
    settings_for(Environment.DEVELOPMENT).validate_for_startup()


def test_the_issuer_is_derived_from_the_supabase_url():
    settings = settings_for(Environment.PRODUCTION, **CONFIGURED)

    assert settings.jwt_issuer == "https://example.supabase.co/auth/v1"
