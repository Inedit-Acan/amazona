"""Apoyo común de las pruebas de frontera numérica (M46, Commit 5c): una base SQLite en memoria, un cliente que NO
relanza los 500 del servidor (para ver el código HTTP que recibe quien llama) y utilidades.

`raise_server_exceptions=False`: con el valor por defecto un 500 se vería como una excepción dentro del test.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.jobs.worker import Worker
from app.main import app

NAN, INF = float("nan"), float("inf")

#: Lo que un cuerpo de error nunca debe contener.
LEAKS = ("Traceback", 'File "', "InvalidOperation", "ZeroDivisionError", "ValueError", "PendingRollback", ".py")


@pytest.fixture()
def boundary_world():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app, raise_server_exceptions=False), session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def rows(session_factory) -> dict[str, int]:
    """Filas de **cada** tabla: «no escribe nada» se mide en todas, no en las que se me ocurran."""
    with session_factory() as session:
        return {
            table.name: session.execute(select(func.count()).select_from(table)).scalar_one()
            for table in Base.metadata.sorted_tables
        }


def post(client: TestClient, url: str, body: dict):
    """`json.dumps` deja pasar NaN e Infinity, que es lo que Starlette también acepta al leer el cuerpo."""
    return client.post(url, content=json.dumps(body), headers={"content-type": "application/json"})


def product_and_quote(client: TestClient) -> tuple[str, str]:
    research = client.post("/api/research/runs", json={"category": "electronics", "max_results": 1}).json()
    product_id = research["candidates"][0]["product_id"]
    sourcing = client.post(
        "/api/sourcing/runs",
        json={
            "product_id": product_id,
            "category": "electronics",
            "destination_region": "mexico",
            "max_results": 1,
        },
    ).json()
    return product_id, sourcing["quotes"][0]["id"]


def drain(session_factory, rounds: int = 14) -> None:
    """Ejecuta el worker contra la misma base: desde el Milestone 32 la API encola y el worker ejecuta."""
    db = session_factory()
    worker = Worker(name="boundary-test-worker")
    try:
        for _ in range(rounds):
            if worker.run_once(db) is None:
                break
    finally:
        db.close()


def assert_clean_422(response, *fields: str, named: bool = False) -> None:
    """Un 422 sin nada interno y con un cuerpo que se puede volver a leer como JSON estricto.

    * `{"detail": "<cadena>"}` (una regla del dominio); con `named=True` además nombra cada campo dado, o
    * `{"detail": [ ... ]}` de esquema con un error por cada campo dado en `loc == ["body", campo]`.
    """
    assert response.status_code == 422, response.text
    body = json.loads(response.text, parse_constant=_no_constants)
    assert set(body) == {"detail"}
    detail = body["detail"]
    if isinstance(detail, str):
        for field in fields if named else ():
            assert field in detail
    else:
        assert isinstance(detail, list) and detail
        assert [error["loc"] for error in detail] == [["body", field] for field in fields]
    for leak in LEAKS:
        assert leak not in response.text


def _no_constants(name: str):
    raise AssertionError(f"the response body contains the non-JSON constant {name}")
