# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""La reconciliación del registro con el estado de pago es de solo lectura y dice la verdad (Milestone 45, ADR 0030
§12 y §13), sobre SQLite y PostgreSQL.

C1 (`Σ CAPTURE = captured_amount`), C2 (`Σ REFUND = refunded_amount`), C3 (cada entrada contra su evento) y C4 (un cobro
con dinero tiene su entrada) se **informan**, nunca se corrigen; un cobro anterior al registro es `outside_ledger`
(informativo, no una divergencia); y mirar no escribe.

C5 (el origen de la entrada contra el de su cobro, su evento y la captura que revierte) y C6 (el origen de un evento
contra el de su cobro) son del Milestone 46 (ADR 0031): con el esquema íntegro no pueden ocurrir, así que las pruebas
**provocan la deriva** quitando las guardas de la base (en PostgreSQL con `session_replication_role = replica`, lo que
hace una restauración con `--disable-triggers`; en SQLite, borrando los disparadores) y comprueban que se informa, con
los motivos, y que no se corrige nada.
"""

import datetime
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from payment_test_support import (
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    deliver,
    events,
    ingress,
    start_attempt,
)
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
from sqlalchemy import event, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry
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


# --- C5 y C6: el origen (Milestone 46, ADR 0031) ----------------------------------------------------------------------

ORIGINS = {"mock": MockPaymentProvider, "sandbox": SandboxPaymentProvider, "real": RealPaymentProvider}
OTHER = {"mock": "sandbox", "sandbox": "real", "real": "mock"}


def drift(db: Session) -> None:
    """Quita las guardas de la base para poder forzar una divergencia de origen que el esquema íntegro impide.

    PostgreSQL: `SET LOCAL session_replication_role = replica` (dura hasta el commit) desactiva claves ajenas y
    disparadores, justo lo que hace una restauración con los disparadores desactivados. SQLite: sin claves ajenas en
    esta base, y se borran los disparadores (la base de la prueba es desechable)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL session_replication_role = replica"))
    else:
        for (name,) in db.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).all():
            db.execute(text(f'DROP TRIGGER "{name}"'))


def set_origin(db: Session, model, row_id: str, origin: str) -> None:
    drift(db)
    db.execute(update(model).where(model.id == row_id).values(provider_kind=origin))
    db.commit()
    db.expire_all()


def only(status: dict, check: str) -> list[dict]:
    return [item for item in status["divergences"]["items"] if item["check"] == check]


@pytest.mark.parametrize("origin", ORIGINS)
def test_a_ledger_whose_facts_all_share_their_origin_is_clean_for_every_origin(db: Session, origin: str):
    provider = ORIGINS[origin]()
    payment = capture(db, provider, new_order(db))
    confirm_refund(db, provider, refund_of(db, provider, payment, "20.00"))

    status = check_ledger(db)

    assert clean(status), status
    assert status["entries"] == 2 and {e.provider_kind for e in entries(db)} == {origin}


def test_a_ledger_with_mock_sandbox_and_real_side_by_side_is_clean_and_each_keeps_its_own_origin(db: Session):
    payments = {}
    for origin, provider_class in ORIGINS.items():
        provider = provider_class()
        payments[origin] = capture(db, provider, new_order(db, name=f"Item {origin}", customer=f"sim_{origin}"))
        confirm_refund(db, provider, refund_of(db, provider, payments[origin], "5.00"))

    assert clean(check_ledger(db)), check_ledger(db)
    assert {e.payment_id: e.provider_kind for e in entries(db)} == {p.id: o for o, p in payments.items()}


@pytest.mark.parametrize("origin", ORIGINS)
def test_c5_an_entry_whose_origin_is_not_its_payments_or_its_events_is_reported_with_both_origins(
    db: Session, origin: str
):
    payment = capture(db, ORIGINS[origin](), new_order(db))
    (entry,) = entries(db)
    set_origin(db, RevenueLedgerEntry, entry.id, OTHER[origin])

    status = check_ledger(db)

    assert status["divergences"]["count"] == 1 and status["outside_ledger"]["count"] == 0
    assert status["divergences"]["items"] == [
        {
            "check": "C5",
            "entry_id": entry.id,
            "payment_id": payment.id,
            "origin": OTHER[origin],
            "payment_origin": origin,
            "event_origin": origin,
            "capture_origin": None,
            "reasons": ["the origin differs from the payment's", "the origin differs from the event's"],
        }
    ]


def test_c5_and_c6_when_only_the_payment_changed_origin_the_entry_and_its_event_both_disagree_with_it(db: Session):
    payment = capture(db, SandboxPaymentProvider(), new_order(db))
    (entry,) = entries(db)
    set_origin(db, Payment, payment.id, "real")

    status = check_ledger(db)

    (c5,) = only(status, "C5")
    assert c5["reasons"] == ["the origin differs from the payment's"]
    assert (c5["origin"], c5["payment_origin"], c5["event_origin"]) == ("sandbox", "real", "sandbox")
    (c6,) = only(status, "C6")
    assert c6["payment_id"] == payment.id and (c6["origin"], c6["payment_origin"]) == ("sandbox", "real")
    assert status["divergences"]["count"] == 2 and entry.id == c5["entry_id"]


def test_c5_and_c6_when_only_the_event_changed_origin_it_disagrees_with_its_payment_and_its_entry(db: Session):
    payment = capture(db, MockPaymentProvider(), new_order(db))
    (entry,) = entries(db)
    set_origin(db, PaymentEvent, entry.payment_event_id, "real")

    status = check_ledger(db)

    (c5,) = only(status, "C5")
    assert c5["reasons"] == ["the origin differs from the event's"]
    assert (c5["origin"], c5["payment_origin"], c5["event_origin"]) == ("mock", "mock", "real")
    (c6,) = only(status, "C6")
    assert c6["event_id"] == entry.payment_event_id and c6["payment_id"] == payment.id
    assert (c6["origin"], c6["payment_origin"]) == ("real", "mock")
    assert status["divergences"]["count"] == 2


def test_c5_a_refund_entry_that_does_not_share_the_origin_of_the_capture_it_reverses_names_that_reason(db: Session):
    provider = SandboxPaymentProvider()
    payment = capture(db, provider, new_order(db))
    confirm_refund(db, provider, refund_of(db, provider, payment, "20.00"))
    capture_row = next(e for e in entries(db) if e.kind == "CAPTURE")
    set_origin(db, RevenueLedgerEntry, capture_row.id, "real")

    status = check_ledger(db)

    by_entry = {item["entry_id"]: item for item in only(status, "C5")}
    refund_row = next(e for e in entries(db) if e.kind == "REFUND")
    assert by_entry[capture_row.id]["reasons"] == [
        "the origin differs from the payment's",
        "the origin differs from the event's",
    ]
    assert by_entry[refund_row.id]["reasons"] == ["the origin differs from the capture it reverses"]
    assert by_entry[refund_row.id]["capture_origin"] == "real" and by_entry[refund_row.id]["origin"] == "sandbox"
    assert status["divergences"]["count"] == 2


def test_c6_an_applied_event_without_an_entry_that_is_linked_to_a_payment_of_another_origin_is_reported(db: Session):
    provider = MockPaymentProvider()
    payment = start_attempt(db, new_order(db), provider)
    deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, payment)  # un evento aplicado, enlazado, sin dinero
    (stored,) = [e for e in events(db) if e.payment_id == payment.id]
    assert entries(db) == [], "the event caused no ledger entry: C6 must not depend on one"
    set_origin(db, PaymentEvent, stored.id, "sandbox")

    status = check_ledger(db)

    assert status["divergences"]["items"] == [
        {
            "check": "C6",
            "event_id": stored.id,
            "payment_id": payment.id,
            "origin": "sandbox",
            "payment_origin": "mock",
        }
    ]


def test_an_unmatched_event_keeps_its_origin_and_is_not_a_divergence_even_if_no_payment_has_it(db: Session):
    provider = SandboxPaymentProvider()
    payment = capture(db, MockPaymentProvider(), new_order(db))  # un cobro `mock`: el único que existe
    headers, raw = provider.simulate_event(
        PaymentEventType.PAYMENT_SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,  # la misma referencia, en otro origen
        client_reference=None,
        amount=None,
    )

    result = ingress(db, provider).receive(provider.name, headers, raw)

    assert result.outcome == "unmatched"
    (stranger,) = [e for e in events(db) if e.provider_kind == "sandbox"]
    assert stranger.payment_id is None and stranger.processing_status == "UNMATCHED"
    assert clean(check_ledger(db)), "an unlinked event has no payment whose origin it could contradict"


def test_an_event_of_another_origin_that_names_a_payment_is_a_conflict_kept_unlinked_and_not_a_divergence(db: Session):
    payment = capture(db, MockPaymentProvider(), new_order(db))
    result = deliver(db, SandboxPaymentProvider(), PaymentEventType.PAYMENT_SUCCEEDED, payment, event_id="evt_x")

    assert result.outcome == "conflict"
    (stranger,) = [e for e in events(db) if e.provider_event_id == "evt_x"]
    assert stranger.provider_kind == "sandbox" and stranger.payment_id is None
    assert clean(check_ledger(db)) and check_ledger(db)["entries"] == 1


def test_reporting_an_origin_divergence_fixes_nothing_and_writes_nothing_however_often_it_is_repeated(
    db: Session, engine
):
    payment = capture(db, SandboxPaymentProvider(), new_order(db))
    (entry,) = entries(db)
    set_origin(db, RevenueLedgerEntry, entry.id, "real")
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    first = check_ledger(db)
    reports = [check_ledger(db) for _ in range(3)]
    status = build_status(db, SETTINGS)["revenue"]["ledger"]

    assert all(report == first for report in reports) and status == first
    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SET"))]
    assert statements and writes == [], writes
    db.expire_all()
    assert db.get(RevenueLedgerEntry, entry.id).provider_kind == "real", "the stored origin is not rewritten"
    assert db.get(Payment, payment.id).provider_kind == "sandbox"


def test_the_listing_is_capped_but_the_count_of_origin_divergences_is_not(db: Session):
    provider = MockPaymentProvider()
    for index in range(3):
        capture(db, provider, new_order(db, name=f"Item {index}", customer=f"sim_c{index}"))
    for entry in entries(db):
        set_origin(db, RevenueLedgerEntry, entry.id, "real")

    status = check_ledger(db, limit=2)

    assert status["divergences"]["count"] == 3 and len(status["divergences"]["items"]) == 2
    assert {item["check"] for item in status["divergences"]["items"]} == {"C5"}


def test_the_scheduled_report_and_the_http_status_carry_origin_divergences(db: Session, client: TestClient):
    capture(db, SandboxPaymentProvider(), new_order(db))
    (entry,) = entries(db)
    set_origin(db, RevenueLedgerEntry, entry.id, "mock")

    result = run_reconcile_report({}, None, db)  # type: ignore[arg-type]
    body = client.get("/api/reconciliation/status").json()

    assert result.detail["revenue_ledger_divergences"] == 1
    (item,) = body["revenue"]["ledger"]["divergences"]["items"]
    assert item["check"] == "C5" and item["origin"] == "mock" and item["payment_origin"] == "sandbox"
    assert "hash" not in str(body["revenue"]).lower()


@pytest.mark.parametrize("origin", ORIGINS)
def test_c1_c2_and_c4_hold_for_every_origin_not_only_the_simulator(db: Session, origin: str, monkeypatch):
    provider = ORIGINS[origin]()
    short = mismatched_capture(db, provider, new_order(db, name="Short"), "12.50")
    db.execute(update(Payment).where(Payment.id == short.id).values(captured_amount=Decimal("12.40")))
    refunded = capture(db, provider, new_order(db, name="Refunded", customer="sim_r"))
    confirm_refund(db, provider, refund_of(db, provider, refunded, "20.00"))
    db.execute(
        update(Payment)
        .where(Payment.id == refunded.id)
        .values(refund_committed_amount=Decimal("30"), refunded_amount=Decimal("30"))
    )
    epoch = aware(entries(db)[0].recorded_at)
    with without_ledger(monkeypatch):
        late = capture(db, provider, new_order(db, name="Late", customer="sim_l"))
    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.payment_id == late.id)
        .values(processed_at=epoch + datetime.timedelta(hours=1))
    )
    db.commit()

    status = check_ledger(db)

    assert sorted((i["check"], i["payment_id"]) for i in status["divergences"]["items"]) == sorted(
        [("C1", short.id), ("C2", refunded.id), ("C4", late.id)]
    )
    assert not only(status, "C5") and not only(status, "C6"), "the amounts diverge, the origin does not"
