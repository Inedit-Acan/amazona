
from app.core.config import Settings, get_settings


def test_settings_loads_defaults_for_local_development():
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql")
    assert settings.redis_url.startswith("redis://")


def test_settings_reads_overrides_from_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_get_settings_returns_a_cached_stable_instance():
    first = get_settings()
    second = get_settings()

    assert first is second


def test_supabase_settings_default_to_empty_and_can_be_overridden(monkeypatch):
    settings = Settings(_env_file=None)
    assert settings.supabase_url == ""
    assert settings.supabase_anon_key == ""
    assert settings.supabase_service_role_key == ""

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")

    overridden = Settings(_env_file=None)
    assert overridden.supabase_url == "https://example.supabase.co"
    assert overridden.supabase_anon_key == "anon-key"
    assert overridden.supabase_service_role_key == "service-role-key"


def test_is_supabase_configured_reflects_whether_credentials_are_set():
    unconfigured = Settings(_env_file=None)
    assert unconfigured.is_supabase_configured is False

    configured = Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon-key",
    )
    assert configured.is_supabase_configured is True
