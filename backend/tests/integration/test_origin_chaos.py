# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""Caos con los tres orígenes del dinero delante (Milestone 46, ADR 0031 §13 y §15).

2A probó cada regla del origen por separado. Aquí se prueba lo que solo se ve **mezclando** `mock`, `sandbox` y `real`
mientras las cosas salen mal: la entrega repetida, el desorden, lo que no empareja, lo que choca, la respuesta que llega
tarde, el proceso que muere entre guardar y aplicar, el reconciliador que pasa dos veces y la configuración que cambia
a mitad.

Dos oráculos independientes de `check_ledger` vigilan cada paso: `check_everything` (M44 + M45 + el origen, escrito a
mano en `m45_invariants_test_support`) y `LedgerWatch` (el registro no se reescribe y un hecho conserva el origen con el
que nació). Y el propio `check_ledger` no debe informar ninguna divergencia.

Los tres orígenes comparten **el mismo nombre de proveedor** (`simulated-payments`): lo que distingue un cobro de otro
es el `kind` que declara el proveedor y se guardó, nunca su nombre.
"""

import datetime
import itertools
import random
from collections import Counter
from decimal import Decimal

import pytest
from m45_invariants_test_support import LedgerWatch, check_everything
from order_test_support import session_factory
from payment_test_support import (
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    deliver,
    events,
    ingress,
    reload,
    start_attempt,
)
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    REFUND_SUCCEEDED,
    SUCCEEDED,
    confirm_refund,
    entries,
    new_order,
    refund_of,
)
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.core.errors import AmazonaError, ConflictError
from app.db.models.external_action import ExternalAction
from app.db.models.payment import Payment, PaymentEvent
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.projection import payment_reference
from app.payments.service import PaymentService
from app.reconciliation.events import EventReconciler
from app.revenue.check import check_ledger
from app.revenue.ledger import RevenueLedger, RevenueLedgerWriteError

ORIGINS = {"mock": MockPaymentProvider, "sandbox": SandboxPaymentProvider, "real": RealPaymentProvider}
EXPIRED = PaymentEventType.PAYMENT_EXPIRED


def signed(provider, kind: PaymentEventType, payment: Payment, **kwargs):
    """Los bytes firmados de un evento, **una sola vez**: reentregarlo es enviar exactamente estos mismos bytes."""
    money = Money.of(kwargs.pop("amount", str(payment.amount)), payment.currency)
    return provider.simulate_event(
        kind, provider_payment_ref=payment.provider_payment_ref, client_reference=payment.id, amount=money, **kwargs
    )


def receive(db: Session, provider, bytes_):
    return ingress(db, provider).receive(provider.name, *bytes_)


def sweep(db: Session) -> None:
    """El reconciliador de eventos, tras envejecer lo recibido (el tiempo no se espera, se envejece la fila)."""
    db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.processing_status == "RECEIVED")
        .values(received_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30))
    )
    db.commit()
    EventReconciler(db, older_than=datetime.timedelta(minutes=1), max_attempts=5).sweep()
    db.expire_all()


def healthy(db: Session) -> None:
    broken = check_everything(db)
    assert broken == [], broken
    status = check_ledger(db)
    assert status["divergences"]["count"] == 0, status["divergences"]


@pytest.fixture()
def fk_db():
    """SQLite con las claves ajenas activas: las claves compuestas del origen son lo que se ejerce."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base

    built = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(built, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(built)
    session = session_factory(built)()
    try:
        yield session
    finally:
        session.close()
        built.dispose()


# --- 1 · Entrega repetida ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ORIGINS)
def test_a_capture_redelivered_many_times_is_one_event_and_one_entry_in_its_own_origin(db: Session, origin: str):
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    bytes_ = signed(provider, SUCCEEDED, payment, event_id="evt_once")

    results = [receive(db, provider, bytes_) for _ in range(4)]

    assert [r.outcome for r in results] == ["applied"] * 4
    assert [r.duplicate for r in results] == [False, True, True, True]
    (entry,) = entries(db)
    assert entry.provider_kind == origin and len(events(db)) == 1
    healthy(db)


@pytest.mark.parametrize("order", list(itertools.permutations(ORIGINS)), ids="-".join)
def test_three_payments_with_one_reference_and_events_with_one_id_never_cross_in_any_arrival_order(
    fk_db: Session, order: tuple[str, ...]
):
    """El mismo id de evento y la misma referencia de cobro en los tres orígenes, entregados en los seis órdenes y cada
    uno **dos veces**: tres eventos, tres entradas y cada evento va solo a su cobro."""
    db = fk_db
    providers = {o: ORIGINS[o]() for o in ORIGINS}
    payments = {}
    for origin in ORIGINS:
        payments[origin] = start_attempt(
            db, new_order(db, name=f"W {origin}", customer=f"sim_{origin}"), providers[origin]
        )
        payments[origin].provider_payment_ref = "pay_same"
    db.commit()
    bytes_of = {
        o: providers[o].simulate_event(
            SUCCEEDED,
            provider_payment_ref="pay_same",
            client_reference=None,
            amount=Money.of("50.00", "EUR"),
            event_id="evt_same",
        )
        for o in ORIGINS
    }

    for origin in (*order, *order):
        receive(db, providers[origin], bytes_of[origin])

    assert {e.provider_kind: e.payment_id for e in events(db)} == {o: p.id for o, p in payments.items()}
    assert {e.provider_kind: e.payment_id for e in entries(db)} == {o: p.id for o, p in payments.items()}
    assert all(Decimal(str(reload(db, p).captured_amount)) == Decimal("50") for p in payments.values())
    healthy(db)


# --- 2 · Eventos fuera de orden ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ORIGINS)
@pytest.mark.parametrize(
    "order", list(itertools.permutations(["capture", "provider_refund", "capture_again"])), ids="-".join
)
def test_events_in_any_order_keep_the_origin_and_invent_nothing(fk_db: Session, origin: str, order: tuple[str, ...]):
    """Un cobro, un reembolso del proveedor y una reentrega, en los seis órdenes y en cada origen: el ingreso es el
    mismo, todo lo que se guarda lleva el origen del cobro y nada se enlaza con otro origen."""
    db = fk_db
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    capture_bytes = signed(provider, SUCCEEDED, payment, event_id="evt_capture")
    refund_bytes = signed(
        provider, REFUND_SUCCEEDED, payment, amount="10.00", provider_refund_ref="re_by_provider", event_id="evt_refund"
    )
    bytes_of = {"capture": capture_bytes, "capture_again": capture_bytes, "provider_refund": refund_bytes}
    watch = LedgerWatch()

    for step in order:
        receive(db, provider, bytes_of[step])
        assert check_everything(db) + watch.check(db) == [], f"{order} after {step}"

    kinds = {e.kind: e for e in entries(db)}
    assert [e.kind for e in entries(db)].count("CAPTURE") == 1
    assert {e.provider_kind for e in entries(db)} == {origin}
    assert {e.provider_kind for e in events(db)} == {origin}
    if "REFUND" in kinds:
        assert kinds["REFUND"].provider_kind == kinds["CAPTURE"].provider_kind == origin
    healthy(db)


# --- 3 · Lo que no empareja y lo que choca ----------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ORIGINS)
def test_an_unmatched_event_keeps_its_origin_and_is_not_applied_later_when_its_payment_appears(
    db: Session, origin: str
):
    provider = ORIGINS[origin]()
    early = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="pay_late",
        client_reference=None,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_early",
    )
    assert receive(db, provider, early).outcome == "unmatched"

    payment = start_attempt(db, new_order(db), provider)
    payment.provider_payment_ref = "pay_late"
    db.commit()
    again = receive(db, provider, early)

    assert again.duplicate and again.outcome == "unmatched", (
        "a settled event is not applied just because the payment came"
    )
    assert entries(db) == [] and Decimal(str(reload(db, payment).captured_amount)) == 0
    (stored,) = events(db)
    assert (stored.provider_kind, stored.processing_status, stored.payment_id) == (origin, "UNMATCHED", None)
    fresh = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="pay_late",
        client_reference=None,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_next",
    )
    assert receive(db, provider, fresh).outcome == "applied"
    assert [e.provider_kind for e in entries(db)] == [origin]
    healthy(db)


@pytest.mark.parametrize("origin", ORIGINS)
def test_a_conflicting_capture_keeps_its_origin_and_never_reaches_the_ledger(db: Session, origin: str):
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    assert deliver(db, provider, SUCCEEDED, payment, event_id="evt_ok").outcome == "applied"

    result = deliver(db, provider, SUCCEEDED, payment, event_id="evt_other_amount", amount="49.00")

    assert result.outcome == "conflict"
    conflict = next(e for e in events(db) if e.provider_event_id == "evt_other_amount")
    assert conflict.provider_kind == origin and conflict.processing_status == "CONFLICT"
    assert [e.provider_kind for e in entries(db)] == [origin] and len(entries(db)) == 1
    healthy(db)


def test_a_stray_event_of_another_origin_is_evidence_with_its_own_origin_and_the_payment_goes_on(db: Session):
    mock, sandbox = MockPaymentProvider(), SandboxPaymentProvider()
    payment = start_attempt(db, new_order(db), mock)

    stray = deliver(db, sandbox, SUCCEEDED, payment, event_id="evt_stray")
    real_one = deliver(db, mock, SUCCEEDED, payment, event_id="evt_real_one")

    assert (stray.outcome, real_one.outcome) == ("conflict", "applied")
    by_id = {e.provider_event_id: e for e in events(db)}
    assert (by_id["evt_stray"].provider_kind, by_id["evt_stray"].payment_id) == ("sandbox", None)
    assert (by_id["evt_real_one"].provider_kind, by_id["evt_real_one"].payment_id) == ("mock", payment.id)
    assert [e.provider_kind for e in entries(db)] == ["mock"]
    healthy(db)


# --- 4 · Respuesta tardía y resultado desconocido ---------------------------------------------------------------------


def action_of(db: Session, payment: Payment) -> ExternalAction:
    return db.scalars(select(ExternalAction).where(ExternalAction.reference == payment_reference(payment.id))).one()


@pytest.mark.parametrize("origin", ORIGINS)
def test_an_unknown_outcome_payment_has_its_origin_from_the_start_and_the_late_lookup_does_not_change_it(
    db: Session, origin: str
):
    provider = ORIGINS[origin]("timeout_after")

    payment = start_attempt(db, new_order(db), provider)

    assert payment.status == "UNKNOWN_OUTCOME" and payment.provider_kind == origin, "the origin is not a result"
    status = ExternalActionService(db).reconcile(action_of(db, payment), provider, {})
    assert status is ActionStatus.SUCCEEDED
    payment = reload(db, payment)
    assert payment.status == "OPEN" and payment.provider_kind == origin
    assert deliver(db, provider, SUCCEEDED, payment).outcome == "applied"
    assert [e.provider_kind for e in entries(db)] == [origin]
    healthy(db)


@pytest.mark.parametrize("origin", ORIGINS)
def test_a_webhook_that_beats_the_lost_response_is_applied_in_the_origin_of_the_payment(db: Session, origin: str):
    provider = ORIGINS[origin]("timeout_after")
    payment = start_attempt(db, new_order(db), provider)
    assert payment.status == "UNKNOWN_OUTCOME"

    result = deliver(db, provider, SUCCEEDED, payment, use_payment_ref=False)

    assert result.outcome == "applied", "the provider says it charged: that is a verified fact, whatever our call saw"
    assert [e.provider_kind for e in entries(db)] == [origin] and reload(db, payment).provider_kind == origin
    ExternalActionService(db).reconcile(action_of(db, payment), provider, {})
    healthy(db)


# --- 5 · Un proceso muere entre guardar y aplicar ---------------------------------------------------------------------


@pytest.mark.parametrize("origin", ORIGINS)
def test_an_event_stored_but_not_applied_is_applied_later_with_the_origin_it_was_stored_with(
    db: Session, origin: str, monkeypatch
):
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    bytes_ = signed(provider, SUCCEEDED, payment)

    def died(self, event_id):
        raise KeyboardInterrupt("the process died between storing the event and applying it")

    with monkeypatch.context() as patch:
        patch.setattr(PaymentService, "apply", died)
        with pytest.raises(KeyboardInterrupt):
            receive(db, provider, bytes_)
    db.rollback()
    (stored,) = events(db)
    assert (stored.processing_status, stored.provider_kind) == ("RECEIVED", origin)

    sweep(db)  # nadie le dice al reconciliador qué origen es: lo lee de lo guardado

    (stored,) = events(db)
    assert (stored.processing_status, stored.provider_kind, stored.payment_id) == ("APPLIED", origin, payment.id)
    assert [e.provider_kind for e in entries(db)] == [origin]
    healthy(db)


@pytest.mark.parametrize("origin", ORIGINS)
def test_a_ledger_write_that_fails_leaves_the_event_received_and_nothing_half_done_in_any_origin(
    db: Session, origin: str, monkeypatch
):
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    real_record = RevenueLedger.record_capture

    def broken(self, **kwargs):
        raise RevenueLedgerWriteError("the ledger could not write")

    with monkeypatch.context() as patch:
        patch.setattr(RevenueLedger, "record_capture", broken)
        with pytest.raises(RevenueLedgerWriteError):
            deliver(db, provider, SUCCEEDED, payment)
        db.rollback()
        (stored,) = events(db)
        assert (stored.processing_status, stored.provider_kind) == ("RECEIVED", origin)
        assert entries(db) == [] and Decimal(str(reload(db, payment).captured_amount)) == 0, "all or nothing"
        sweep(db)  # sigue roto: se cuenta el intento y el evento sigue ahí
        assert events(db)[0].processing_status == "RECEIVED" and entries(db) == []

    assert RevenueLedger.record_capture is real_record
    sweep(db)  # el registro vuelve: se aplica con el origen guardado
    (stored,) = events(db)
    assert (stored.processing_status, stored.provider_kind) == ("APPLIED", origin)
    assert [e.provider_kind for e in entries(db)] == [origin]
    healthy(db)


# --- 6 · Reconciliar otra vez ----------------------------------------------------------------------------------------


def test_reconciling_again_and_again_changes_nothing_and_keeps_every_origin(db: Session):
    for origin, provider_class in ORIGINS.items():
        provider = provider_class()
        payment = start_attempt(db, new_order(db, name=f"W {origin}", customer=f"sim_{origin}"), provider)
        deliver(db, provider, SUCCEEDED, payment)
        confirm_refund(db, provider, refund_of(db, provider, payment, "5.00"))
    snapshot = [(e.id, e.kind, e.provider_kind, e.amount) for e in entries(db)]
    ledger = check_ledger(db)

    for _ in range(3):
        sweep(db)
        assert check_ledger(db) == ledger

    assert [(e.id, e.kind, e.provider_kind, e.amount) for e in entries(db)] == snapshot
    assert len(snapshot) == 6
    healthy(db)


# --- 7 · La configuración cambia a mitad ------------------------------------------------------------------------------


def test_when_the_configured_provider_changes_midway_every_fact_keeps_the_origin_it_was_born_with(db: Session):
    mock, sandbox = MockPaymentProvider(), SandboxPaymentProvider()
    payment = start_attempt(db, new_order(db), mock)  # nace `mock`; después la configuración apunta a `sandbox`

    assert deliver(db, mock, SUCCEEDED, payment, event_id="evt_cap").outcome == "applied"
    with pytest.raises(ConflictError):
        refund_of(db, sandbox, payment, "5.00")  # pedirlo al proveedor nuevo no cambia de qué origen es el cobro
    refund = refund_of(db, mock, payment, "5.00")
    stray = confirm_refund(db, sandbox, refund, event_id="evt_refund_from_sandbox")
    assert stray.outcome == "conflict"
    assert confirm_refund(db, mock, refund, event_id="evt_refund_from_mock").outcome == "applied"

    assert {e.provider_kind for e in entries(db)} == {"mock"} and len(entries(db)) == 2
    assert reload(db, payment).provider_kind == "mock"
    by_id = {e.provider_event_id: e for e in events(db)}
    assert (by_id["evt_refund_from_sandbox"].provider_kind, by_id["evt_refund_from_sandbox"].payment_id) == (
        "sandbox",
        None,
    )
    healthy(db)


# --- 8 · Una tormenta aleatoria con los tres orígenes ---------------------------------------------------------------


@pytest.mark.parametrize("seed", range(8))
def test_a_random_storm_across_the_three_origins_never_mixes_them(fk_db: Session, seed: int):
    """Cuarenta operaciones al azar (abrir, capturar, reentregar, evento ajeno, evento sin cobro, reembolsar), con los
    tres orígenes mezclados. Tras **cada** paso: los oráculos de M44, M45 y del origen, el registro que no se reescribe,
    y ni una divergencia en `check_ledger`. Un rechazo legítimo (`AmazonaError`) no es un fallo; una mezcla sí."""
    db = fk_db
    rng = random.Random(seed)
    providers = {o: ORIGINS[o]() for o in ORIGINS}
    watch = LedgerWatch()
    opened: list[tuple[str, str]] = []  # (payment_id, origin)
    history: list[tuple[str, tuple]] = []  # (origin, bytes firmados) para reentregar
    counter = itertools.count(1)
    outcomes: Counter[str] = Counter()

    def new_payment() -> None:
        origin = rng.choice(list(ORIGINS))
        n = next(counter)
        payment = start_attempt(db, new_order(db, name=f"W{n}", customer=f"sim_{n}"), providers[origin])
        opened.append((payment.id, origin))

    def capture_one() -> None:
        payment_id, origin = rng.choice(opened)
        payment = db.get(Payment, payment_id)
        bytes_ = signed(providers[origin], SUCCEEDED, payment, event_id=f"evt_{next(counter)}")
        history.append((origin, bytes_))
        outcomes[receive(db, providers[origin], bytes_).outcome] += 1

    def redeliver() -> None:
        origin, bytes_ = rng.choice(history)
        outcomes[receive(db, providers[origin], bytes_).outcome] += 1

    def stray() -> None:
        payment_id, origin = rng.choice(opened)
        other = rng.choice([o for o in ORIGINS if o != origin])
        payment = db.get(Payment, payment_id)
        bytes_ = signed(providers[other], rng.choice([SUCCEEDED, EXPIRED]), payment, event_id=f"evt_{next(counter)}")
        history.append((other, bytes_))
        outcomes[receive(db, providers[other], bytes_).outcome] += 1

    def unmatched() -> None:
        origin = rng.choice(list(ORIGINS))
        bytes_ = providers[origin].simulate_event(
            SUCCEEDED,
            provider_payment_ref=f"pay_nobody_{next(counter)}",
            client_reference=None,
            amount=Money.of("50.00", "EUR"),
        )
        history.append((origin, bytes_))
        outcomes[receive(db, providers[origin], bytes_).outcome] += 1

    def refund_one() -> None:
        payment_id, origin = rng.choice(opened)
        payment = db.get(Payment, payment_id)
        refund = refund_of(db, providers[origin], payment, "1.00")
        confirm_refund(db, providers[origin], refund, event_id=f"evt_{next(counter)}")

    operations = [new_payment, capture_one, capture_one, redeliver, stray, unmatched, refund_one]
    new_payment()
    for step in range(40):
        operation = rng.choice(operations) if history or operations[0] is new_payment else new_payment
        if operation in (redeliver,) and not history:
            operation = new_payment
        try:
            operation()
        except AmazonaError:
            db.rollback()  # un rechazo legítimo (un reembolso que no cabe, un cobro que no admite más)
        broken = check_everything(db) + watch.check(db)
        assert broken == [], f"seed {seed}, step {step} ({operation.__name__}): {broken}"
        assert check_ledger(db)["divergences"]["count"] == 0, f"seed {seed}, step {step} ({operation.__name__})"

    assert outcomes["applied"] >= 1 and outcomes["conflict"] + outcomes["unmatched"] >= 1, dict(outcomes)
    assert {e.provider_kind for e in entries(db)} <= set(ORIGINS)
    for entry in entries(db):
        payment = db.get(Payment, entry.payment_id)
        assert entry.provider_kind == payment.provider_kind
