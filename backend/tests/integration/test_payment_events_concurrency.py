"""Los eventos de pago y los intentos de cobro, con carreras reales (Milestone 44, ADR 0028).

SQLite serializa las transacciones y nunca reproduce una carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el
orden en que se intercalen, un pago se confirma **una vez**, un pedido tiene **un** cobro canónico, el dinero que
existió queda registrado, y un pedido no se cancela y se cobra a la vez.
"""

import threading
from decimal import Decimal

from order_test_support import add_product
from payment_test_support import (
    REQUESTER,  # noqa: E402 - agrupado con los gestos de la prueba
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    ingress,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent
from app.money.money import Money
from app.orders.payment_attempts import PaymentAttemptService
from app.orders.service import OrderService
from app.payments.port import PaymentEventType

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED


def run_together(engine, jobs: list) -> list:
    barrier = threading.Barrier(len(jobs))
    results: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                outcome = job(session)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada tarea es el dato
                outcome = exc
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def capture(provider, payment_id: str, ref: str | None, event_id: str, amount: str = "50.00"):
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=ref,
        client_reference=payment_id,
        amount=Money.of(amount, "EUR"),
        event_id=event_id,
    )

    def job(session: Session):
        return ingress(session, provider).receive(provider.name, headers, raw)

    return job


def prepare(engine, provider):
    with Session(engine) as db:
        order = add_order(db, add_product(db))
        return order.id


def errors(results: list) -> list[Exception]:
    return [r for r in results if isinstance(r, Exception)]


def test_the_same_event_delivered_twelve_times_at_once_is_applied_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = prepare(engine, provider)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            payment_id, ref = payment.id, payment.provider_payment_ref

        results = run_together(engine, [capture(provider, payment_id, ref, "evt_same")] * 12)

        assert not errors(results), errors(results)
        assert sorted({r.outcome for r in results}) == ["applied"]
        assert sum(1 for r in results if not r.duplicate) == 1, "exactly one delivery stored the event"
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
            payment = db.get(Payment, payment_id)
            assert payment.status == "SUCCEEDED" and Decimal(str(payment.captured_amount)) == Decimal("50")
            assert db.get(Order, order_id).status == "PAID"


def test_two_different_capture_events_for_the_same_payment_count_the_money_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = prepare(engine, provider)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            payment_id, ref = payment.id, payment.provider_payment_ref

        results = run_together(
            engine, [capture(provider, payment_id, ref, "evt_a"), capture(provider, payment_id, ref, "evt_b")]
        )

        assert not errors(results), errors(results)
        assert sorted(r.outcome for r in results) == ["applied", "stale"]
        with Session(engine) as db:
            total = db.scalar(select(func.sum(Payment.captured_amount)).where(Payment.order_id == order_id))
            assert Decimal(str(total)) == Decimal("50")


def test_two_attempts_captured_at_the_same_time_leave_one_canonical_payment_and_one_duplicate_with_all_the_money():
    """La carrera del índice: ninguna de las dos capturas se pierde, y como mucho una es `SUCCEEDED`."""
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = prepare(engine, provider)
        with Session(engine) as db:
            order = db.get(Order, order_id)
            first = start_attempt(db, order, provider)
            deliver(db, provider, PaymentEventType.PAYMENT_EXPIRED, first)
            second = start_attempt(db, order, provider)
            first_id, first_ref = first.id, first.provider_payment_ref
            second_id, second_ref = second.id, second.provider_payment_ref

        results = run_together(
            engine,
            [
                capture(provider, first_id, first_ref, "evt_first"),
                capture(provider, second_id, second_ref, "evt_second"),
            ],
        )

        assert not errors(results), errors(results)
        assert all(r.outcome == "applied" for r in results)
        with Session(engine) as db:
            statuses = sorted(p.status for p in db.scalars(select(Payment).where(Payment.order_id == order_id)))
            assert statuses == ["DUPLICATE_CAPTURE", "SUCCEEDED"], statuses
            total = db.scalar(select(func.sum(Payment.captured_amount)).where(Payment.order_id == order_id))
            assert Decimal(str(total)) == Decimal("100"), "the money that really existed is all recorded"
            assert db.get(Order, order_id).status == "PAID"
            duplicate = db.scalars(select(Payment).where(Payment.status == "DUPLICATE_CAPTURE")).one()
            canonical = db.scalars(select(Payment).where(Payment.status == "SUCCEEDED")).one()
            assert duplicate.duplicate_of_payment_id == canonical.id


def test_ten_simultaneous_attempts_on_one_order_leave_one_alive():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = prepare(engine, provider)

        def attempt(session: Session):
            return PaymentAttemptService(session, settings=SIMULATION, provider=provider).start(
                order_id, requester=REQUESTER
            )

        results = run_together(engine, [attempt] * 10)

        opened = [r for r in results if isinstance(r, Payment)]
        refused = [r for r in results if isinstance(r, ConflictError)]
        assert len(opened) == 1 and len(refused) == 9, [type(r).__name__ for r in results]
        with Session(engine) as db:
            alive = db.scalars(
                select(Payment).where(
                    Payment.order_id == order_id,
                    Payment.status.in_(["REQUESTED", "OPENING", "UNKNOWN_OUTCOME", "OPEN"]),
                )
            ).all()
            assert len(alive) == 1
        assert len(provider.calls) == 1, "the provider was asked once"


def test_cancelling_and_charging_the_same_order_at_once_never_do_both():
    for _ in range(6):
        with ephemeral_postgres() as engine:
            provider = ScriptedPaymentProvider()
            order_id = prepare(engine, provider)

            def attempt(session: Session):
                return PaymentAttemptService(session, settings=SIMULATION, provider=provider).start(
                    order_id, requester=REQUESTER
                )

            def cancel(session: Session):
                return OrderService(session, settings=SIMULATION).cancel(order_id, actor="t")

            results = run_together(engine, [attempt, cancel])

            with Session(engine) as db:
                order = db.get(Order, order_id)
                alive = db.scalars(
                    select(Payment).where(Payment.order_id == order_id, Payment.status.in_(["OPEN", "OPENING"]))
                ).all()
                assert not (order.status == "CANCELLED" and alive), "a cancelled order cannot have a live charge"
                assert sum(1 for r in results if not isinstance(r, Exception)) == 1, results
