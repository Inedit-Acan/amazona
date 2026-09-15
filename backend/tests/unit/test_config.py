import os

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
