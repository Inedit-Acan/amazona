"""El origen del dinero con reconciliadores y lectores concurrentes, sobre PostgreSQL de verdad (M46, ADR 0031).

Cada hilo tiene su propia sesión, en una base PostgreSQL efímera con el esquema de los modelos, y arrancan juntos
tras una barrera. Lo que se afirma son invariantes, no tiempos:

- **Varios reconciliadores y varias reentregas a la vez** sobre eventos ya guardados de los tres orígenes aplican cada
  evento **una** vez, con el origen con el que se guardó; el dinero se cuenta una vez y el registro cuadra.
- **`check_ledger` leyendo mientras otros hilos escriben** nunca informa un C5 ni un C6 falsos: cada uno es una sola
  sentencia sobre filas que se confirman de una vez con su cobro, así que no hay instante en que un lector vea el
  registro «a medias». (C1 y C4, que miran en varias sentencias, sí pueden ver una foto intermedia: ya era así y no se
  afirma nada de ellos aquí.)
"""

import datetime
import threading
from decimal import Decimal

import pytest
from m45_invariants_test_support import check_everything
from order_test_support import add_product
from payment_test_support import (
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    add_order,
    ingress,
    run_together,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService
from app.reconciliation.events import EventReconciler
from app.revenue.check import check_ledger

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
ORIGINS = {"mock": MockPaymentProvider, "sandbox": SandboxPaymentProvider, "real": RealPaymentProvider}


def signed(provider, payment: Payment, event_id: str):
    return provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of(str(payment.amount), payment.currency),
        event_id=event_id,
    )


def store_without_applying(engine, provider, payment_id: str, event_id: str):
    """Un proceso que muere entre guardar el evento verificado y aplicarlo. Devuelve los bytes que llegaron."""
    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        bytes_ = signed(provider, payment, event_id)

        def died(self, event_id):
            raise KeyboardInterrupt("the process died between storing the event and applying it")

        real_apply = PaymentService.apply
        PaymentService.apply = died  # type: ignore[method-assign]
        try:
            with pytest.raises(KeyboardInterrupt):
                ingress(db, provider).receive(provider.name, *bytes_)
        finally:
            PaymentService.apply = real_apply  # type: ignore[method-assign]
        db.rollback()
    return bytes_


def age_received(engine) -> None:
    with Session(engine) as db:
        db.execute(
            update(PaymentEvent)
            .where(PaymentEvent.processing_status == "RECEIVED")
            .values(received_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30))
        )
        db.commit()


def test_reconcilers_and_redeliveries_at_once_apply_each_stored_event_once_in_its_own_origin():
    with ephemeral_postgres() as engine:
        providers = {o: ORIGINS[o]() for o in ORIGINS}
        payment_ids: dict[str, str] = {}
        redeliveries = []
        for index, (origin, provider) in enumerate(providers.items()):
            with Session(engine) as db:
                payment = start_attempt(db, add_order(db, add_product(db, name=f"W {index}")), provider)
                payment_ids[origin] = payment.id
            redeliveries.append((provider, store_without_applying(engine, provider, payment.id, f"evt_{origin}")))
        age_received(engine)

        def sweep(session: Session):
            return EventReconciler(session, older_than=datetime.timedelta(minutes=1), max_attempts=5).sweep()

        def redeliver(provider, bytes_):
            def job(session: Session):
                return ingress(session, provider).receive(provider.name, *bytes_)

            return job

        jobs = [sweep, sweep, sweep] + [redeliver(p, b) for p, b in redeliveries] * 2
        results = run_together(engine, jobs)

        assert not [r for r in results if isinstance(r, Exception)], results
        with Session(engine) as db:
            stored = {e.provider_kind: (e.processing_status, e.payment_id) for e in db.scalars(select(PaymentEvent))}
            assert stored == {o: ("APPLIED", payment_ids[o]) for o in ORIGINS}
            ledger = {e.payment_id: e.provider_kind for e in db.scalars(select(RevenueLedgerEntry))}
            assert ledger == {payment_ids[o]: o for o in ORIGINS}, "one entry per payment, in its own origin"
            for origin, payment_id in payment_ids.items():
                payment = db.get(Payment, payment_id)
                assert payment.provider_kind == origin and Decimal(str(payment.captured_amount)) == Decimal("50")
            assert check_everything(db) == []
            status = check_ledger(db)
            assert status["divergences"]["count"] == 0 and status["entries"] == 3


def test_check_ledger_reading_while_others_write_never_reports_a_false_origin_divergence():
    with ephemeral_postgres() as engine:
        providers = {o: ORIGINS[o]() for o in ORIGINS}
        plan: list[tuple[str, str, str]] = []  # (origin, payment_id, event_id)
        for index in range(12):
            origin = list(ORIGINS)[index % 3]
            with Session(engine) as db:
                payment = start_attempt(db, add_order(db, add_product(db, name=f"W {index}")), providers[origin])
                plan.append((origin, payment.id, f"evt_{index}"))

        done = threading.Event()
        barrier = threading.Barrier(5)
        seen_origin_divergences: list[dict] = []
        reads = [0]
        errors: list[BaseException] = []

        def writer(items: list[tuple[str, str, str]]) -> None:
            try:
                barrier.wait(timeout=10)
                for origin, payment_id, event_id in items:
                    with Session(engine) as db:
                        payment = db.get(Payment, payment_id)
                        provider = providers[origin]
                        ingress(db, provider).receive(provider.name, *signed(provider, payment, event_id))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def reader() -> None:
            try:
                barrier.wait(timeout=10)
                while True:
                    finished = done.is_set()  # una última lectura DESPUÉS de que terminen los escritores
                    with Session(engine) as db:
                        status = check_ledger(db, limit=1000)
                    seen_origin_divergences.extend(
                        i for i in status["divergences"]["items"] if i["check"] in ("C5", "C6")
                    )
                    reads[0] += 1
                    if finished:
                        return
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        writers = [threading.Thread(target=writer, args=(plan[i::4],)) for i in range(4)]
        reading = threading.Thread(target=reader)
        for thread in (*writers, reading):
            thread.start()
        for thread in writers:
            thread.join(timeout=120)
        done.set()
        reading.join(timeout=120)

        assert not errors, errors
        assert reads[0] >= 2, "the reader must have read at least while and after the writers"
        assert seen_origin_divergences == [], seen_origin_divergences
        with Session(engine) as db:
            assert len(list(db.scalars(select(RevenueLedgerEntry)))) == 12
            assert check_everything(db) == []
            assert check_ledger(db)["divergences"]["count"] == 0
