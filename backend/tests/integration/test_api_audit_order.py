"""`GET /api/audit`: orden, límite y cursor (micro-commit 5A del Director ejecutivo).

El contrato anterior devolvía `ORDER BY created_at ASC LIMIT 500`: las 500 entradas más ANTIGUAS, sin forma de pedir
las más recientes ni de paginar. El contrato nuevo es ADITIVO: sin parámetros, el comportamiento es el de antes; con
`order`, `limit`, `since` y `before` se puede pedir lo más reciente y paginar hacia atrás con un cursor de keyset
`(created_at, id)`, sin `offset` y sin duplicar ni perder filas con empates de `created_at`.

Se prueba en SQLite (que descarta la zona al leer) y en PostgreSQL (`timestamptz`, que la conserva): las dos formas
de guardar el instante tienen que dar el mismo resultado. En PostgreSQL solo si hay uno local o efímero alcanzable.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.session import get_db
from app.main import app

UTC = datetime.UTC
T0 = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
FIELDS = {"id", "actor", "action", "resource", "before", "after", "correlation_id", "created_at"}


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def engine(request):
    """Una base por módulo y backend (una por prueba tardaría minutos); cada prueba la vacía."""
    if request.param == "sqlite":
        sqlite = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(sqlite)
        yield sqlite
        sqlite.dispose()
    else:
        with ephemeral_postgres() as postgres:
            yield postgres


@pytest.fixture()
def session_factory(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.query(AuditLog).delete()
        session.commit()
    return factory


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seed(session_factory):
    def add(rows: list[tuple[str, datetime.datetime, str]]) -> None:
        """`(id, created_at en UTC, correlation_id)`. El orden de inserción no es el orden de lectura."""
        with session_factory() as session:
            for row_id, created_at, correlation_id in rows:
                session.add(
                    AuditLog(
                        id=row_id,
                        actor="ceo",
                        action="project.created",
                        resource=f"project:{row_id}",
                        correlation_id=correlation_id,
                        created_at=created_at,
                    )
                )
            session.commit()

    return add


def at(seconds: int, micro: int = 0) -> datetime.datetime:
    return T0 + datetime.timedelta(seconds=seconds, microseconds=micro)


def ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


def instant(text: str) -> datetime.datetime:
    """El instante de un `created_at` de la respuesta: SQLite lo devuelve sin zona (UTC), PostgreSQL con ella."""
    value = datetime.datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def cursor_of(row: dict) -> str:
    """El cursor de la fila: su `created_at` TAL CUAL lo devolvió la API, una coma y su id."""
    return f"{row['created_at']},{row['id']}"


def distinct(count: int, prefix: str = "r", correlation: str = "c") -> list[tuple[str, datetime.datetime, str]]:
    """`count` filas con instantes distintos; el id crece con el tiempo."""
    return [(f"{prefix}{i:04d}", at(i), correlation) for i in range(count)]


# --- A. sin parámetros: exactamente el comportamiento de antes ------------------------------------


def test_without_parameters_it_is_ascending_and_returns_the_500_oldest(client, seed):
    rows = distinct(520)
    seed(list(reversed(rows)))  # se insertan al revés: el orden de lectura no es el de inserción
    response = client.get("/api/audit")
    assert ids(response) == [row[0] for row in rows[:500]]  # las 500 más antiguas, la más antigua primero
    assert "r0519" not in ids(response) and "r0500" not in ids(response)


def test_without_parameters_the_response_is_what_the_old_query_returned(client, seed, session_factory):
    seed(distinct(40))
    with session_factory() as session:
        old = session.query(AuditLog).order_by(AuditLog.created_at).limit(500).all()
    assert ids(client.get("/api/audit")) == [row.id for row in old]
    assert set(client.get("/api/audit").json()[0]) == FIELDS


def test_without_parameters_ties_are_broken_by_id_ascending(client, seed):
    seed([("c", at(5), "x"), ("a", at(5), "x"), ("b", at(5), "x"), ("z", at(1), "x")])
    assert ids(client.get("/api/audit")) == ["z", "a", "b", "c"]


def test_explicit_defaults_equal_no_parameters(client, seed):
    seed(distinct(30))
    assert ids(client.get("/api/audit?order=asc&limit=500")) == ids(client.get("/api/audit"))


# --- B-F. order y limit ---------------------------------------------------------------------------


def test_order_desc_returns_the_newest_first(client, seed):
    seed(distinct(30))
    assert ids(client.get("/api/audit?order=desc")) == [f"r{i:04d}" for i in reversed(range(30))]


def test_order_desc_with_a_tie_orders_by_id_descending(client, seed):
    seed([("b", at(5), "x"), ("a", at(5), "x"), ("c", at(5), "x"), ("z", at(9), "x"), ("y", at(1), "x")])
    assert ids(client.get("/api/audit?order=desc")) == ["z", "c", "b", "a", "y"]


def test_order_asc_with_a_tie_orders_by_id_ascending(client, seed):
    seed([("b", at(5), "x"), ("a", at(5), "x"), ("c", at(5), "x"), ("z", at(9), "x"), ("y", at(1), "x")])
    assert ids(client.get("/api/audit?order=asc")) == ["y", "a", "b", "c", "z"]


def test_microseconds_decide_the_order_before_the_id(client, seed):
    seed([("a", at(5, 2), "x"), ("z", at(5, 1), "x")])
    assert ids(client.get("/api/audit?order=desc")) == ["a", "z"]


def test_order_desc_limit_5_returns_exactly_the_5_newest(client, seed):
    seed(distinct(520))
    assert ids(client.get("/api/audit?order=desc&limit=5")) == ["r0519", "r0518", "r0517", "r0516", "r0515"]


def test_the_newest_entries_are_reachable_even_with_more_than_500_rows(client, seed):
    seed(distinct(600))
    assert ids(client.get("/api/audit?order=desc&limit=1")) == ["r0599"]
    assert len(ids(client.get("/api/audit?order=desc"))) == 500
    assert ids(client.get("/api/audit?order=desc"))[0] == "r0599"


def test_limit_1_and_limit_500_are_accepted(client, seed):
    seed(distinct(3))
    assert ids(client.get("/api/audit?limit=1")) == ["r0000"]
    assert ids(client.get("/api/audit?limit=500")) == ["r0000", "r0001", "r0002"]


def test_limit_larger_than_the_table_returns_what_there_is(client, seed):
    seed(distinct(3))
    assert len(ids(client.get("/api/audit?order=desc&limit=400"))) == 3


# --- G-I. validación: nada se normaliza en silencio -----------------------------------------------


@pytest.mark.parametrize("limit", ["0", "-1", "501", "1000", "abc", "", "1.5"])
def test_an_invalid_limit_is_a_422(client, seed, limit):
    seed(distinct(3))
    assert client.get(f"/api/audit?limit={limit}").status_code == 422


@pytest.mark.parametrize("order", ["sideways", "DESC", "Asc", "", "newest", "1"])
def test_an_invalid_order_is_a_422(client, seed, order):
    seed(distinct(3))
    assert client.get(f"/api/audit?order={order}").status_code == 422


# --- J. since -------------------------------------------------------------------------------------


def test_since_is_inclusive_and_filters_older_rows(client, seed):
    seed(distinct(10))
    since = at(6).isoformat()
    assert ids(client.get("/api/audit", params={"since": since})) == ["r0006", "r0007", "r0008", "r0009"]
    assert ids(client.get("/api/audit", params={"since": since, "order": "desc", "limit": 2})) == ["r0009", "r0008"]


def test_since_in_the_future_returns_nothing_not_an_error(client, seed):
    seed(distinct(3))
    assert ids(client.get("/api/audit", params={"since": at(10_000).isoformat()})) == []


def test_since_distinguishes_microseconds(client, seed):
    seed([("a", at(5, 1), "x"), ("b", at(5, 2), "x"), ("c", at(5, 3), "x")])
    assert ids(client.get("/api/audit", params={"since": at(5, 2).isoformat()})) == ["b", "c"]


# --- K-L. before: cursor de keyset ----------------------------------------------------------------


def pages(client, size: int, extra: dict | None = None) -> list[list[str]]:
    result: list[list[str]] = []
    params: dict = {"order": "desc", "limit": size, **(extra or {})}
    for _ in range(60):  # un tope: un servidor que ignorase `before` devolvería la misma página para siempre
        response = client.get("/api/audit", params=params)
        assert response.status_code == 200, response.text
        rows = response.json()
        if not rows:
            return result
        result.append([row["id"] for row in rows])
        params = {**params, "before": cursor_of(rows[-1])}
    raise AssertionError("pagination did not end: the cursor is not advancing")


def test_before_paginates_backwards_without_duplicates_or_gaps(client, seed):
    seed(distinct(25))
    result = pages(client, 10)
    assert [len(page) for page in result] == [10, 10, 5]
    assert [i for page in result for i in page] == [f"r{i:04d}" for i in reversed(range(25))]


def test_before_with_ties_on_created_at_neither_loses_nor_repeats_rows(client, seed):
    tied = [(f"t{i:02d}", at(7), "x") for i in range(12)]  # doce filas con el MISMO instante
    seed(tied + [("old", at(1), "x"), ("new", at(9), "x")])
    for size in (1, 2, 5, 7, 12, 13):
        flat = [i for page in pages(client, size) for i in page]
        assert flat == ["new"] + [f"t{i:02d}" for i in reversed(range(12))] + ["old"], size


def test_before_is_exclusive_of_the_cursor_row(client, seed):
    seed(distinct(5))
    first = client.get("/api/audit?order=desc&limit=2").json()
    assert ids(client.get("/api/audit", params={"order": "desc", "before": cursor_of(first[-1])})) == [
        "r0002",
        "r0001",
        "r0000",
    ]


def test_before_alone_with_asc_returns_the_oldest_of_those_older_than_the_cursor(client, seed):
    seed(distinct(6))
    cursor = f"{at(4).isoformat()},r0004"
    assert ids(client.get("/api/audit", params={"before": cursor, "limit": 2})) == ["r0000", "r0001"]


def test_before_at_the_oldest_row_returns_nothing(client, seed):
    seed(distinct(3))
    assert ids(client.get("/api/audit", params={"order": "desc", "before": f"{at(0).isoformat()},r0000"})) == []


def test_before_uses_the_id_to_break_a_tie_with_the_cursor_instant(client, seed):
    seed([("a", at(5), "x"), ("b", at(5), "x"), ("c", at(5), "x")])
    assert ids(client.get("/api/audit", params={"order": "desc", "before": f"{at(5).isoformat()},b"})) == ["a"]
    assert ids(client.get("/api/audit", params={"order": "desc", "before": f"{at(5).isoformat()},a"})) == []


def test_since_and_before_together_bound_a_window(client, seed):
    seed(distinct(10))
    params = {"order": "desc", "since": at(3).isoformat(), "before": f"{at(8).isoformat()},r0008"}
    assert ids(client.get("/api/audit", params=params)) == ["r0007", "r0006", "r0005", "r0004", "r0003"]


# --- M-N. correlation_id sigue igual y se combina -------------------------------------------------


def mixed(seed):
    rows = [(f"a{i:02d}", at(2 * i), "alpha") for i in range(10)] + [
        (f"b{i:02d}", at(2 * i + 1), "beta") for i in range(10)
    ]
    seed(rows)


def test_correlation_id_still_filters_without_other_parameters(client, seed):
    mixed(seed)
    assert ids(client.get("/api/audit?correlation_id=alpha")) == [f"a{i:02d}" for i in range(10)]
    assert ids(client.get("/api/audit?correlation_id=nope")) == []


def test_correlation_id_with_order_desc_and_limit(client, seed):
    mixed(seed)
    assert ids(client.get("/api/audit?correlation_id=beta&order=desc&limit=3")) == ["b09", "b08", "b07"]


def test_correlation_id_with_since(client, seed):
    mixed(seed)
    assert ids(client.get("/api/audit", params={"correlation_id": "alpha", "since": at(14).isoformat()})) == [
        "a07",
        "a08",
        "a09",
    ]


def test_correlation_id_with_before(client, seed):
    mixed(seed)
    params = {"correlation_id": "alpha", "order": "desc", "before": f"{at(6).isoformat()},a03", "limit": 2}
    assert ids(client.get("/api/audit", params=params)) == ["a02", "a01"]


def test_correlation_id_pages_never_leak_the_other_correlation(client, seed):
    mixed(seed)
    flat = [i for page in pages(client, 3, {"correlation_id": "beta"}) for i in page]
    assert flat == [f"b{i:02d}" for i in reversed(range(10))]


# --- O-P. instantes con zona y entradas inválidas -------------------------------------------------


def test_since_with_a_zone_offset_is_the_same_instant_as_in_utc(client, seed):
    seed(distinct(10))
    utc = ids(client.get("/api/audit", params={"since": "2026-10-01T12:00:06Z"}))
    plus = ids(client.get("/api/audit", params={"since": "2026-10-01T14:00:06+02:00"}))
    minus = ids(client.get("/api/audit", params={"since": "2026-10-01T07:00:06-05:00"}))
    assert utc == plus == minus == ["r0006", "r0007", "r0008", "r0009"]


def test_a_naive_timestamp_is_read_as_utc(client, seed):
    seed(distinct(10))
    assert ids(client.get("/api/audit", params={"since": "2026-10-01T12:00:06"})) == [
        "r0006",
        "r0007",
        "r0008",
        "r0009",
    ]
    assert ids(client.get("/api/audit", params={"since": "2026-10-01 12:00:06"})) == [
        "r0006",
        "r0007",
        "r0008",
        "r0009",
    ]


def test_the_cursor_works_with_an_offset_and_with_z(client, seed):
    seed(distinct(5))
    base = {"order": "desc"}
    assert ids(client.get("/api/audit", params={**base, "before": "2026-10-01T14:00:03+02:00,r0003"})) == [
        "r0002",
        "r0001",
        "r0000",
    ]
    assert ids(client.get("/api/audit", params={**base, "before": "2026-10-01T12:00:03Z,r0003"})) == [
        "r0002",
        "r0001",
        "r0000",
    ]
    assert ids(client.get("/api/audit", params={**base, "before": "2026-10-01T12:00:03,r0003"})) == [
        "r0002",
        "r0001",
        "r0000",
    ]


def test_the_created_at_of_a_response_round_trips_as_a_cursor(client, seed):
    seed([("a", at(5, 123456), "x"), ("b", at(5, 123456), "x"), ("c", at(5, 123457), "x")])
    first = client.get("/api/audit?order=desc&limit=1").json()[0]
    assert first["id"] == "c" and instant(first["created_at"]) == at(5, 123457)
    assert ids(client.get("/api/audit", params={"order": "desc", "before": cursor_of(first)})) == ["b", "a"]


@pytest.mark.parametrize(
    "since",
    [
        "garbage",
        "2026-13-45T00:00:00Z",
        "2026-10-01",
        "1700000000",
        "2026-10-01T12:00:06 02:00",
        "",
        "tomorrow",
        "NaN",
        "9999-12-31T23:59:59-05:00",  # no cabe en UTC: un 422, no un 500
        "0001-01-01T00:00:00+05:00",
    ],
)
def test_an_invalid_since_is_a_422(client, seed, since):
    seed(distinct(3))
    assert client.get("/api/audit", params={"since": since}).status_code == 422


@pytest.mark.parametrize(
    "before",
    [
        "garbage",
        "2026-10-01T12:00:03Z",  # sin id
        "2026-10-01T12:00:03Z,",  # id vacío
        ",r0003",  # sin instante
        "yesterday,r0003",
        "2026-10-01,r0003",  # solo fecha
        "1700000000,r0003",
        "",
    ],
)
def test_an_invalid_before_is_a_422(client, seed, before):
    seed(distinct(3))
    assert client.get("/api/audit", params={"before": before}).status_code == 422


def test_invalid_parameters_do_not_fall_back_to_the_default_answer(client, seed):
    seed(distinct(3))
    response = client.get("/api/audit", params={"order": "up", "limit": 2})
    assert response.status_code == 422
    assert not isinstance(response.json(), list)


# --- determinismo y forma -------------------------------------------------------------------------


def test_the_same_request_twice_gives_the_same_answer(client, seed):
    seed([("b", at(5), "x"), ("a", at(5), "x"), ("c", at(6), "x")])
    for query in ("", "?order=desc", "?order=desc&limit=2"):
        assert ids(client.get(f"/api/audit{query}")) == ids(client.get(f"/api/audit{query}"))


def test_the_response_schema_is_unchanged_for_every_form_of_the_request(client, seed):
    seed(distinct(3))
    for query in ("", "?order=desc", "?limit=2", "?since=2026-10-01T12:00:00Z"):
        for row in client.get(f"/api/audit{query}").json():
            assert set(row) == FIELDS
            assert instant(row["created_at"]) >= T0


def test_an_empty_audit_trail_is_an_empty_list_for_every_form(client):
    for query in ("", "?order=desc", "?limit=1", "?since=2026-10-01T12:00:00Z", "?before=2026-10-01T12:00:00Z,x"):
        response = client.get(f"/api/audit{query}")
        assert response.status_code == 200 and response.json() == []
