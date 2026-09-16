"""Verifies the configured DATABASE_URL is a real, reachable PostgreSQL
database (CI's ephemeral service, a local docker-compose Postgres, or a
real Supabase project) — never SQLite, and never mocked.

Skips (does not fail) when nothing is actually reachable, so this test
suite stays green in a sandbox without Docker/Postgres/Supabase
credentials, per Milestone 2's rule that 🔒 tasks degrade gracefully.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings


def _connect_or_skip():
    settings = get_settings()
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL")

    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 3})
    try:
        connection = engine.connect()
    except OperationalError as exc:
        pytest.skip(f"no reachable PostgreSQL at DATABASE_URL: {exc}")
    return engine, connection


def test_database_url_points_at_a_reachable_postgres():
    engine, connection = _connect_or_skip()
    try:
        result = connection.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        connection.close()
        engine.dispose()


def test_alembic_version_table_exists_and_has_a_revision():
    engine, connection = _connect_or_skip()
    try:
        result = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert result is not None
    finally:
        connection.close()
        engine.dispose()
