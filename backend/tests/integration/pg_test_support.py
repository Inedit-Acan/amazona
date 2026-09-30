"""Apoyo compartido de las pruebas que necesitan un PostgreSQL de verdad (hardening pre-M44).

Módulo auxiliar de tests, **no** un test. Una carrera entre transacciones solo existe en
una base que tenga transacciones de verdad: SQLite las serializa todas y nunca la
reproduce. Por eso estas pruebas crean una **base de datos efímera**, con el esquema de
los modelos, y la borran al terminar: ningún dato de prueba queda en la base configurada.

Solo contra un PostgreSQL local o efímero (el servicio del CI, el de desarrollo): si
`DATABASE_URL` apunta a otro sitio, o no hay PostgreSQL alcanzable, se omiten.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.base import Base

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@contextmanager
def ephemeral_postgres() -> Iterator[Engine]:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL")
    if url.host not in LOCAL_HOSTS:
        pytest.skip("these tests create and drop a database: only against a local or ephemeral PostgreSQL")

    name = f"amazona_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"no reachable PostgreSQL at DATABASE_URL: {exc}")
    except Exception as exc:  # noqa: BLE001 - sin permiso para crear bases: no es un fallo del producto
        admin.dispose()
        pytest.skip(f"cannot create a scratch database here: {exc}")

    engine = create_engine(url.set(database=name), pool_size=24, max_overflow=8)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
