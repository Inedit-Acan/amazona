# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""El estado de la reconciliación es de solo lectura y dice la verdad (Milestone 45, ADR 0029 §8), sobre SQLite y
PostgreSQL.

Lo que se afirma: la fotografía de lo abierto, de lo desconocido (con su edad) y de los eventos topados es la que hay
en la base; un `GET` **no escribe**
(ni cierra, ni repite, ni corrige); no lleva cuerpos ni hashes; y el valor provisional del techo se informa como
provisional.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from reconciliation_test_support import (  # noqa: F401 - fixtures de pytest
    age_action,
    ago,
    authorise_budget,
    db,
    engine,
    factory,
    make_action,
    stored_event,
)
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.jobs.recurring import RECONCILE_JOB_TYPES, RecurringScheduler
from app.main import app
from app.reconciliation.report import build_status

SETTINGS = Settings(_env_file=None)


@pytest.fixture()
def client(db: Session, factory, engine):
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


def test_an_empty_system_reports_nothing_open_and_says_the_ceiling_is_provisional(db: Session):
    status = build_status(db, SETTINGS)

    assert status["enabled"] is True
    assert status["actions"]["open"] == {
        state: {"count": 0, "oldest_age_seconds": None} for state in ("PENDING", "CALLING", "UNKNOWN_OUTCOME")
    }
    assert status["actions"]["unknown_outcomes"] == []
    assert status["events"]["waiting"] == {"count": 0, "oldest_age_seconds": None}
    assert status["events"]["capped"] == {"count": 0, "items": []}
    assert status["runs"] == dict.fromkeys(RECONCILE_JOB_TYPES)
    view = status["settings"]
    assert view["external_call_max_seconds"] == 120 and view["external_call_max_seconds_is_provisional"] is True
    assert (view["actions_older_than_minutes"], view["events_older_than_minutes"], view["event_max_attempts"]) == (
        15,
        5,
        5,
    )


def test_a_configured_ceiling_is_not_reported_as_provisional(db: Session):
    status = build_status(db, Settings(_env_file=None, external_call_max_seconds=45))

    assert status["settings"]["external_call_max_seconds"] == 45
    assert status["settings"]["external_call_max_seconds_is_provisional"] is False


def test_the_photograph_counts_and_ages_what_is_open_unknown_waiting_and_capped(db: Session):
    authorise_budget(db)
    pending = make_action(db, state="PENDING", reference="pipeline_step:run-1:a")
    calling = make_action(db, state="CALLING", reference="pipeline_step:run-1:b")
    unknown_old = make_action(db, state="UNKNOWN_OUTCOME", reference="pipeline_step:run-1:c", operation="activate_ads")
    unknown_new = make_action(db, state="UNKNOWN_OUTCOME", reference="pipeline_step:run-1:d")
    age_action(db, pending, updated=ago(minutes=10))
    age_action(db, calling, call_started=ago(minutes=20), updated=ago(minutes=1))
    age_action(db, unknown_old, call_started=ago(hours=2), updated=ago(minutes=1))
    age_action(db, unknown_new, call_started=ago(minutes=3), updated=ago(minutes=1))
    stored_event(db, event_id="waiting", received_ago=datetime.timedelta(minutes=9), attempts=2)
    stored_event(db, event_id="capped-1", received_ago=datetime.timedelta(hours=1), attempts=5)
    stored_event(db, event_id="applied", status="APPLIED")

    status = build_status(db, SETTINGS)

    opened = status["actions"]["open"]
    assert opened["PENDING"]["count"] == 1 and 595 <= opened["PENDING"]["oldest_age_seconds"] <= 640
    assert opened["CALLING"]["count"] == 1 and 1195 <= opened["CALLING"]["oldest_age_seconds"] <= 1240
    assert opened["UNKNOWN_OUTCOME"]["count"] == 2 and 7195 <= opened["UNKNOWN_OUTCOME"]["oldest_age_seconds"] <= 7240
    listed = status["actions"]["unknown_outcomes"]
    assert [item["id"] for item in listed] == [unknown_old.id, unknown_new.id], "the oldest unknown first"
    assert listed[0]["operation"] == "activate_ads" and listed[0]["reference"] == "pipeline_step:run-1:c"
    assert status["events"]["waiting"]["count"] == 1 and 530 <= status["events"]["waiting"]["oldest_age_seconds"] <= 580
    capped = status["events"]["capped"]
    assert (
        capped["count"] == 1
        and capped["items"][0]["attempts"] == 5
        and capped["items"][0]["event_type"] == "payment.succeeded"
    )


def test_the_status_lists_a_bounded_number_of_items_and_counts_the_rest(db: Session):
    authorise_budget(db, hard_limit=100_000)
    for n in range(25):
        make_action(db, state="UNKNOWN_OUTCOME", reference=f"pipeline_step:run-1:u{n}", amount=None)
    for n in range(60):
        stored_event(db, event_id=f"capped-{n}", attempts=5)

    status = build_status(db, SETTINGS)

    assert (
        status["actions"]["open"]["UNKNOWN_OUTCOME"]["count"] == 25 and len(status["actions"]["unknown_outcomes"]) == 20
    )
    assert status["events"]["capped"]["count"] == 60 and len(status["events"]["capped"]["items"]) == 50


def test_the_last_run_of_each_job_type_is_reported(db: Session):
    RecurringScheduler(SETTINGS, clock=lambda: datetime.datetime(2026, 10, 3, 12, 0, tzinfo=datetime.UTC)).enqueue_due(
        db
    )

    runs = build_status(db, SETTINGS)["runs"]

    assert set(runs) == set(RECONCILE_JOB_TYPES)
    assert all(run is not None and run["status"] == "QUEUED" and run["completed_at"] is None for run in runs.values())


# --- Por HTTP -------------------------------------------------------------------------------------------------------


def test_the_route_returns_the_same_photograph_in_the_published_shape(db: Session, client: TestClient):
    authorise_budget(db)
    make_action(db, state="UNKNOWN_OUTCOME")
    stored_event(db, event_id="capped", attempts=5)

    response = client.get("/api/reconciliation/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"enabled", "settings", "actions", "events", "runs"}
    assert body["actions"]["open"]["UNKNOWN_OUTCOME"]["count"] == 1
    assert body["events"]["capped"]["count"] == 1
    assert body["settings"]["external_call_max_seconds_is_provisional"] is True


def test_a_get_writes_nothing_closes_nothing_and_leaks_no_body_or_hash(db: Session, client: TestClient, engine):
    authorise_budget(db)
    action = make_action(db, state="UNKNOWN_OUTCOME")
    age_action(db, action, call_started=ago(days=30), updated=ago(days=30))
    stored_event(db, event_id="capped", attempts=5)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    responses = [client.get("/api/reconciliation/status") for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 200]
    writes = [
        s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT", "RELEASE"))
    ]
    assert statements and writes == [], writes
    text = responses[0].text
    assert "payload_hash" not in text and "hash-capped" not in text and "idempotency_key" not in text
    assert responses[0].json()["actions"]["open"]["UNKNOWN_OUTCOME"]["count"] == 1, (
        "reading did not close the unknown outcome"
    )
