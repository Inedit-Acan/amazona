# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""Las rutas de agregados de ingresos son solo lectura y no prometen más de lo que el registro demuestra
(Milestone 45, ADR 0030), sobre HTTP, con SQLite y PostgreSQL.

Lo que se afirma: los tres `GET` responden con importes como **texto exacto**; ninguna respuesta lleva margen,
beneficio, coste, impuestos, IVA/OSS, caja ni comisiones (y dicen que no son contabilidad); los parámetros
inválidos son un 422 y nunca una respuesta engañosa; un método que escribe no existe; la zona horaria se normaliza
a UTC; la paginación sigue su cursor sin repetir ni saltar; y ninguna lectura escribe.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from payment_test_support import deliver, start_attempt
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    EXPIRED,
    SUCCEEDED,
    ScriptedPaymentProvider,
    confirm_refund,
    new_order,
    refund_of,
    reload,
)
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app

SETTINGS = Settings(_env_file=None)
UTC = datetime.UTC
#: Nombres de campo que una respuesta de ingresos **no** puede tener: el registro no demuestra nada de esto.
FORBIDDEN_KEYS = {
    "margin", "profit", "cost", "costs", "tax", "taxes", "vat", "vat_oss", "oss", "cash", "fee", "fees",
    "commission", "commissions", "gateway_fees", "balance",
}  # fmt: skip


def at(day: int, hour: int = 12) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, hour, 0, tzinfo=UTC)


@pytest.fixture()
def provider() -> ScriptedPaymentProvider:
    return ScriptedPaymentProvider()


@pytest.fixture()
def client(db: Session, factory):
    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture()
def world(db: Session, provider) -> None:
    """Un cobro EUR con reembolso, un duplicado EUR y un cobro USD: 5 entradas, 3 clases... y las dos monedas."""
    a = start_attempt(db, new_order(db, "A", "sim_a"), provider)
    deliver(db, provider, SUCCEEDED, a, occurred_at=at(1))
    confirm_refund(db, provider, refund_of(db, provider, a, "20.00"), occurred_at=at(2))
    order_b = new_order(db, "B", "sim_b")
    first = start_attempt(db, order_b, provider)
    deliver(db, provider, EXPIRED, first)
    second = start_attempt(db, order_b, provider)
    deliver(db, provider, SUCCEEDED, second, occurred_at=at(3))
    deliver(db, provider, SUCCEEDED, reload(db, first), occurred_at=at(3))
    d = start_attempt(db, new_order(db, "D", "sim_d", price="15.00", currency="USD"), provider)
    deliver(db, provider, SUCCEEDED, d, occurred_at=at(6))


def keys(document) -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for name, value in document.items():
            found.add(name)
            found |= keys(value)
    elif isinstance(document, list):
        for item in document:
            found |= keys(item)
    return found


# --- Qué responde ---------------------------------------------------------------------------------------------------


def test_the_summary_answers_with_exact_text_amounts_and_says_it_is_not_accounting(client: TestClient, world):
    response = client.get("/api/revenue/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entries"] == 5
    eur = next(r for r in body["verified"] if r["currency"] == "EUR")
    assert (eur["revenue"], eur["refunds"], eur["net"]) == ("100.0000", "20.0000", "80.0000")
    assert all(isinstance(eur[k], str) for k in ("revenue", "refunds", "net")), "never a JSON number (a float)"
    assert body["under_review"][0]["classification"] == "DUPLICATE_RECEIPT"
    assert body["consolidated_eur"]["net"] == "80.0000"
    assert [r["currency"] for r in body["non_aggregable_currencies"]] == ["USD"]
    assert body["scope"]["is_accounting_ledger"] is False
    assert {"costs", "margin", "profit", "taxes", "vat_oss", "cash", "gateway_fees", "fx_conversion"} <= set(
        body["scope"]["excludes"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/revenue/summary",
        "/api/revenue/series?from=2026-10-01T00:00:00Z&to=2026-10-10T00:00:00Z",
        "/api/revenue/series?granularity=month&from=2026-10-01T00:00:00Z&to=2026-11-01T00:00:00Z",
        "/api/revenue/entries",
    ],
)
def test_no_response_carries_margin_profit_cost_taxes_cash_or_fees(client: TestClient, world, path):
    response = client.get(path)

    assert response.status_code == 200, response.text
    assert not keys(response.json()) & FORBIDDEN_KEYS, keys(response.json()) & FORBIDDEN_KEYS


def test_the_series_answers_by_bucket_and_currency(client: TestClient, world):
    response = client.get("/api/revenue/series?from=2026-10-01T00:00:00Z&to=2026-10-10T00:00:00Z")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["granularity"] == "day"
    assert [(b["bucket"], b["currency"]) for b in body["buckets"]] == [
        ("2026-10-01", "EUR"),
        ("2026-10-02", "EUR"),
        ("2026-10-03", "EUR"),
        ("2026-10-06", "USD"),
    ]
    assert body["buckets"][1]["net"] == "-20.0000"


def test_the_entries_page_lists_the_facts_behind_the_figures(client: TestClient, world):
    body = client.get("/api/revenue/entries?limit=2").json()

    assert len(body["items"]) == 2 and body["has_more"] is True and body["next_cursor"]
    assert set(body["items"][0]) == {
        "id", "kind", "classification", "payment_event_id", "payment_id", "order_id", "refund_id",
        "capture_entry_id", "amount", "currency", "occurred_at", "recorded_at",
    }  # fmt: skip
    assert body["items"][0]["currency"] == "USD" and body["items"][0]["amount"] == "30.0000"
    assert body["items"][0]["occurred_at"].endswith("+00:00"), "always UTC, whatever the time zone of the session"
    from app.revenue.pagination import EntryCursor

    assert EntryCursor.decode(body["next_cursor"]).occurred_at.utcoffset() == datetime.timedelta(0)


def test_following_the_cursor_over_http_visits_every_entry_once(client: TestClient, world):
    seen, url = [], "/api/revenue/entries?limit=2"
    while True:
        body = client.get(url).json()
        seen += [item["id"] for item in body["items"]]
        if not body["has_more"]:
            break
        url = f"/api/revenue/entries?limit=2&cursor={body['next_cursor']}"

    assert len(seen) == len(set(seen)) == 5


# --- Parámetros ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/api/revenue/summary?from=2026-10-05T00:00:00Z&to=2026-10-01T00:00:00Z",
        "/api/revenue/summary?from=2026-10-05T00:00:00Z&to=2026-10-05T00:00:00Z",
        "/api/revenue/summary?from=yesterday",
        "/api/revenue/series?granularity=hour",
        "/api/revenue/series?from=2024-01-01T00:00:00Z&to=2026-01-01T00:00:00Z",
        "/api/revenue/series?granularity=month&from=2020-01-01T00:00:00Z&to=2026-01-01T00:00:00Z",
        "/api/revenue/entries?limit=0",
        "/api/revenue/entries?limit=201",
        "/api/revenue/entries?currency=eur",
        "/api/revenue/entries?currency=EURO",
        "/api/revenue/entries?classification=REVENUE",
        "/api/revenue/entries?kind=REVERSAL",
        "/api/revenue/entries?cursor=not-a-cursor",
        "/api/revenue/entries?cursor=" + "a" * 400,
    ],
)
def test_an_invalid_parameter_is_a_422_never_a_misleading_answer(client: TestClient, path):
    response = client.get(path)

    assert response.status_code == 422, (path, response.status_code, response.text)


@pytest.mark.parametrize("path", ["/api/revenue/summary", "/api/revenue/series", "/api/revenue/entries"])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_nothing_that_writes_exists_on_these_routes(client: TestClient, path, method):
    assert getattr(client, method)(path).status_code == 405


def test_a_date_without_a_zone_is_utc_and_another_zone_is_carried_to_utc(client: TestClient, world):
    plain = client.get("/api/revenue/summary?from=2026-10-03&to=2026-10-04").json()
    zulu = client.get("/api/revenue/summary?from=2026-10-03T00:00:00Z&to=2026-10-04T00:00:00Z").json()
    offset = client.get("/api/revenue/summary?from=2026-10-03T02:00:00%2B02:00&to=2026-10-04T02:00:00%2B02:00").json()

    assert plain["entries"] == zulu["entries"] == offset["entries"] == 2
    assert plain["period"] == zulu["period"] == offset["period"]
    assert zulu["period"]["from"] == "2026-10-03T00:00:00+00:00"
    shifted = client.get("/api/revenue/summary?from=2026-10-03T00:00:00%2B02:00&to=2026-10-04T00:00:00%2B02:00").json()
    assert shifted["period"]["from"] == "2026-10-02T22:00:00+00:00", "midnight at +02:00 is 22:00 UTC the day before"


def test_the_period_filters_the_http_summary(client: TestClient, world):
    body = client.get("/api/revenue/summary?from=2026-10-06T00:00:00Z").json()

    assert [r["currency"] for r in body["verified"]] == ["USD"] and body["consolidated_eur"] is None


# --- Solo lectura -----------------------------------------------------------------------------------------------------


def test_the_http_reads_write_nothing(client: TestClient, world, engine):
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    responses = [
        client.get("/api/revenue/summary"),
        client.get("/api/revenue/series?from=2026-10-01T00:00:00Z&to=2026-10-10T00:00:00Z"),
        client.get("/api/revenue/entries?limit=2"),
    ]

    assert [r.status_code for r in responses] == [200, 200, 200]
    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT"))]
    assert statements and writes == [], writes
