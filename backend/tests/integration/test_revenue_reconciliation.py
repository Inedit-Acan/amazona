# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""La reconciliación del registro con el estado de pago es de solo lectura y dice la verdad (Milestone 45, ADR 0030
§12 y §13), sobre SQLite y PostgreSQL.

C1 (`Σ CAPTURE = captured_amount`), C2 (`Σ REFUND = refunded_amount`), C3 (cada entrada contra su evento) y C4 (un cobro
con dinero tiene su entrada) se **informan**, nunca se corrigen; un cobro anterior al registro es `outside_ledger`
(informativo, no una divergencia); y mirar no escribe.
"""

import datetime
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from payment_test_support import deliver, events
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    ScriptedPaymentProvider,
    aware,
    capture,
    capture_entry,
    confirm_refund,
    duplicate_pair,
    entries,
    mismatched_capture,
    new_order,
    refund_of,
)
from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.payment import Payment, PaymentEvent
from app.db.session import get_db
from app.jobs.handlers import run_reconcile_report
from app.main import app
from app.payments.port import PaymentEventType
from app.reconciliation.report import build_status
from app.revenue.check import check_ledger
from app.revenue.ledger import RevenueLedger

SETTINGS = Settings(_env_file=None)


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


def clean(status: dict) -> bool:
    return status["divergences"]["count"] == 0 and status["outside_ledger"]["count"] == 0


@contextmanager
def without_ledger(monkeypatch):
    """Un cobro capturado «antes del registro»: la captura se aplica y la entrada no se escribe."""
    with monkeypatch.context() as patch:
        patch.setattr(RevenueLedger, "record_capture", lambda self, **kwargs: None)
        yield


# --- Un sistema que cuadra ------------------------------------------------------------------------------------------


def test_an_empty_ledger_reconciles_with_nothing(db: Session):
    assert check_ledger(db) == {
        "entries": 0,
        "divergences": {"count": 0, "items": []},
        "outside_ledger": {"count": 0, "items": []},
    }


def test_captures_duplicates_mismatches_and_refunds_reconcile_with_the_payments(db: Session, provider):
    order = new_order(db)
    canonical, duplicate = duplicate_pair(db, provider, order)
    odd = mismatched_capture(db, provider, new_order(db, name="Gadget", customer="sim_other"), "12.50")
    confirm_refund(db, provider, refund_of(db, provider, canonical, "20.00"))
    confirm_refund(db, provider, refund_of(db, provider, duplicate, "50.00", reason="duplicate_capture"))
    confirm_refund(db, provider, refund_of(db, provider, odd, "12.50", reason="capture_mismatch"))

    status = check_ledger(db)

    assert clean(status), status
    assert status["entries"] == len(entries(db)) == 6


# --- Las divergencias se informan; nunca se corrigen ----------------------------------------------------------------


def test_c1_a_payment_whose_captured_money_differs_from_its_capture_entries_is_reported_and_left_alone(
    db: Session, provider
):
    payment = mismatched_capture(db, provider, new_order(db), "12.50")
    db.execute(update(Payment).where(Payment.id == payment.id).values(captured_amount=Decimal("12.40")))
    db.commit()

    status = check_ledger(db)

    assert status["divergences"]["items"] == [
        {"check": "C1", "payment_id": payment.id, "currency": "EUR", "payment": "12.4000", "ledger": "12.5000"}
    ]
    assert status["divergences"]["count"] == 1 and status["outside_ledger"]["count"] == 0
    db.expire_all()
    assert Decimal(str(db.get(Payment, payment.id).captured_amount)) == Decimal("12.4"), "reporting does not fix"
    assert [e.amount for e in entries(db)] == [Decimal("12.5")]


def test_c2_refunded_money_that_the_ledger_does_not_have_is_reported(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    confirm_refund(db, provider, refund_of(db, provider, payment, "20.00"))
    db.execute(
        update(Payment)
        .where(Payment.id == payment.id)
        .values(refund_committed_amount=Decimal("30"), refunded_amount=Decimal("30"))
    )
    db.commit()

    status = check_ledger(db)

    assert status["divergences"]["items"] == [
        {"check": "C2", "payment_id": payment.id, "currency": "EUR", "payment": "30.0000", "ledger": "20.0000"}
    ]


def test_c3_an_entry_whose_event_is_not_what_it_claims_is_reported_with_its_reasons(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    (entry,) = entries(db)

    db.execute(
        update(PaymentEvent).where(PaymentEvent.id == entry.payment_event_id).values(processing_status="CONFLICT")
    )
    db.commit()
    (item,) = check_ledger(db)["divergences"]["items"]
    assert item["check"] == "C3" and item["entry_id"] == entry.id and item["payment_id"] == payment.id
    assert item["reasons"] == ["the event is not APPLIED"]

    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.id == entry.payment_event_id)
        .values(processing_status="APPLIED", amount=Decimal("49"), currency="USD", event_type="refund.succeeded")
    )
    db.commit()
    (item,) = check_ledger(db)["divergences"]["items"]
    assert sorted(item["reasons"]) == sorted(
        [
            "the event type does not produce this kind of entry",
            "the amount differs from the event",
            "the currency differs from the event",
        ]
    )


def test_c4_a_payment_with_money_captured_after_the_ledger_began_but_without_its_entry_is_a_divergence(
    db: Session, provider, monkeypatch
):
    capture(db, provider, new_order(db))  # el registro ya existe: tiene una entrada
    epoch = aware(entries(db)[0].recorded_at)
    with without_ledger(monkeypatch):
        late = capture(db, provider, new_order(db, name="Gadget", customer="sim_other"))
    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.payment_id == late.id)
        .values(processed_at=epoch + datetime.timedelta(hours=1))
    )
    db.commit()

    status = check_ledger(db)

    assert status["outside_ledger"]["count"] == 0
    assert status["divergences"]["items"] == [
        {"check": "C4", "payment_id": late.id, "currency": "EUR", "payment": "50.0000", "ledger": "0.0000"}
    ]


# --- Datos anteriores al registro: informativo, no un fallo ---------------------------------------------------------


def test_a_payment_captured_before_the_ledger_is_outside_the_ledger_and_not_a_divergence(
    db: Session, provider, monkeypatch
):
    with without_ledger(monkeypatch):
        legacy = capture(db, provider, new_order(db))
    assert check_ledger(db)["outside_ledger"]["count"] == 1, "with an empty ledger, nothing can be told apart"

    capture(db, provider, new_order(db, name="Gadget", customer="sim_other"))  # empieza el registro
    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.payment_id == legacy.id)
        .values(processed_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1))
    )
    db.commit()

    status = check_ledger(db)

    assert status["divergences"]["count"] == 0
    assert status["outside_ledger"]["items"] == [{"payment_id": legacy.id, "currency": "EUR", "payment": "50.0000"}]
    assert status["entries"] == 1


def test_a_refund_of_a_payment_outside_the_ledger_does_not_make_it_a_divergence(db: Session, provider, monkeypatch):
    with without_ledger(monkeypatch):
        legacy = capture(db, provider, new_order(db))
    confirm_refund(db, provider, refund_of(db, provider, legacy, "20.00"))

    status = check_ledger(db)

    assert status["divergences"]["count"] == 0 and status["outside_ledger"]["count"] == 1
    assert entries(db) == []


# --- Solo lectura y a la vista ---------------------------------------------------------------------------------------


def test_the_status_carries_the_ledger_and_the_pending_evidence_and_writes_nothing(db: Session, provider, engine):
    payment = capture(db, provider, new_order(db))
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment, event_id="evt_other", amount="49.00")
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    revenue = build_status(db, SETTINGS)["revenue"]

    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert statements and writes == [], writes
    assert set(revenue) == {"ledger", "pending_evidence"}
    assert clean(revenue["ledger"]) and revenue["ledger"]["entries"] == 1
    assert revenue["pending_evidence"]["count"] == 1
    assert len(events(db)) == 2 and len(entries(db)) == 1, "reading closed and created nothing"
    assert capture_entry(db, payment).amount == Decimal("50")


def test_the_http_status_exposes_the_revenue_block_without_bodies_or_hashes(db: Session, client: TestClient, provider):
    payment = capture(db, provider, new_order(db))
    deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment, event_id="evt_other", amount="49.00")

    response = client.get("/api/reconciliation/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"enabled", "settings", "actions", "events", "runs", "revenue"}
    assert body["revenue"]["pending_evidence"]["by_currency"] == [
        {"currency": "EUR", "event_type": "payment.succeeded", "count": 1, "amount": "49.0000"}
    ]
    assert "payload_hash" not in response.text and "hash" not in str(body["revenue"]).lower()


def test_the_scheduled_report_counts_what_the_ledger_found(db: Session, provider):
    payment = capture(db, provider, new_order(db))
    db.execute(
        update(Payment)
        .where(Payment.id == payment.id)
        .values(refund_committed_amount=Decimal("5"), refunded_amount=Decimal("5"))
    )
    db.commit()  # fmt: skip

    result = run_reconcile_report({}, None, db)  # type: ignore[arg-type]

    assert result.detail["revenue_ledger_divergences"] == 1
    assert result.detail["revenue_outside_ledger"] == 0
    assert result.detail["pending_economic_evidence"] == 0
