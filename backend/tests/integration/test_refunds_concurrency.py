"""Los reembolsos con carreras reales (Milestone 44, ADR 0028 §5).

SQLite serializa las transacciones y nunca reproduce una carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el
orden en que se intercalen, **jamás se aparta más de lo cobrado**, jamás se envía al proveedor un reembolso que no cabe,
y un mismo hecho se cuenta una vez.
"""

from decimal import Decimal

from order_test_support import add_product
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    ingress,
    run_together,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models.order import Order
from app.db.models.payment import Payment, Refund
from app.money.money import Money
from app.orders.errors import OutcomeUnknownBlockError
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType


def captured_payment(engine, provider) -> str:
    with Session(engine) as db:
        order = add_order(db, add_product(db))
        payment = start_attempt(db, db.get(Order, order.id), provider)
        deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
        return payment.id


def refund_job(provider, payment_id: str, amount: str):
    def job(session: Session):
        return RefundService(session, settings=SIMULATION, provider=provider).request(
            payment_id, amount=Money.of(amount, "EUR"), reason="customer_request", requester=REQUESTER
        )

    return job


def figures(engine, payment_id: str) -> tuple[Decimal, Decimal, Decimal]:
    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        return (
            Decimal(str(payment.captured_amount)),
            Decimal(str(payment.refund_committed_amount)),
            Decimal(str(payment.refunded_amount)),
        )


def test_ten_simultaneous_refunds_never_set_aside_more_than_was_captured():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id = captured_payment(engine, provider)
        calls_before = len(provider.calls)

        results = run_together(engine, [refund_job(provider, payment_id, "10.00")] * 10)

        done = [r for r in results if isinstance(r, Refund)]
        refused = [r for r in results if isinstance(r, ConflictError)]
        assert len(done) == 5 and len(refused) == 5, [type(r).__name__ for r in results]
        assert figures(engine, payment_id) == (Decimal(50), Decimal(50), Decimal(0))
        assert len(provider.calls) - calls_before == 5, "no refund that did not fit ever reached the provider"
        with Session(engine) as db:
            total = db.scalar(select(func.sum(Refund.amount)).where(Refund.payment_id == payment_id))
            assert Decimal(str(total)) == Decimal(50)


def test_two_refunds_that_do_not_fit_together_leave_exactly_one():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id = captured_payment(engine, provider)

        results = run_together(engine, [refund_job(provider, payment_id, "30.00")] * 2)

        assert sorted(type(r).__name__ for r in results) == ["ConflictError", "Refund"]
        assert figures(engine, payment_id)[1] == Decimal(30)


def test_the_same_confirmation_delivered_eight_times_at_once_is_counted_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id = captured_payment(engine, provider)
        with Session(engine) as db:
            refund = refund_job(provider, payment_id, "10.00")(db)
            payment = db.get(Payment, payment_id)
            headers, raw = provider.simulate_event(
                PaymentEventType.REFUND_SUCCEEDED,
                provider_payment_ref=payment.provider_payment_ref,
                provider_refund_ref=refund.provider_refund_ref,
                client_reference=refund.id,
                amount=Money.of("10.00", "EUR"),
                event_id="evt_refund_once",
            )

        def deliver_it(session: Session):
            return ingress(session, provider).receive(provider.name, headers, raw)

        results = run_together(engine, [deliver_it] * 8)

        assert not [r for r in results if isinstance(r, Exception)], results
        assert sum(1 for r in results if not r.duplicate) == 1
        assert figures(engine, payment_id) == (Decimal(50), Decimal(10), Decimal(10))
        with Session(engine) as db:
            assert db.get(Refund, refund.id).status == "SUCCEEDED"


def test_two_different_confirmations_of_the_same_refund_count_the_money_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id = captured_payment(engine, provider)
        with Session(engine) as db:
            refund = refund_job(provider, payment_id, "10.00")(db)
            payment = db.get(Payment, payment_id)

            def event(event_id: str):
                headers, raw = provider.simulate_event(
                    PaymentEventType.REFUND_SUCCEEDED,
                    provider_payment_ref=payment.provider_payment_ref,
                    provider_refund_ref=refund.provider_refund_ref,
                    client_reference=refund.id,
                    amount=Money.of("10.00", "EUR"),
                    event_id=event_id,
                )
                return lambda session: ingress(session, provider).receive(provider.name, headers, raw)

            jobs = [event("evt_a"), event("evt_b")]

        results = run_together(engine, jobs)

        assert not [r for r in results if isinstance(r, Exception)], results
        assert sorted(r.outcome for r in results) == ["applied", "stale"]
        assert figures(engine, payment_id) == (Decimal(50), Decimal(10), Decimal(10))


def test_a_refund_and_a_failure_confirmation_of_another_never_leave_more_set_aside_than_captured():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id = captured_payment(engine, provider)
        with Session(engine) as db:
            first = refund_job(provider, payment_id, "50.00")(db)
            payment = db.get(Payment, payment_id)
            headers, raw = provider.simulate_event(
                PaymentEventType.REFUND_FAILED,
                provider_payment_ref=payment.provider_payment_ref,
                provider_refund_ref=first.provider_refund_ref,
                client_reference=first.id,
                amount=Money.of("50.00", "EUR"),
                event_id="evt_refund_failed",
            )

        def free_it(session: Session):
            return ingress(session, provider).receive(provider.name, headers, raw)

        results = run_together(engine, [free_it, refund_job(provider, payment_id, "50.00")])

        assert not [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)], results
        captured, committed, refunded = figures(engine, payment_id)
        assert captured == Decimal(50) and refunded == Decimal(0)
        assert Decimal(0) <= committed <= captured, "whichever came first, nothing was over-reserved"
        with Session(engine) as db:
            statuses = sorted(r.status for r in db.scalars(select(Refund)))
            reserved = sum(
                Decimal(str(r.amount)) for r in db.scalars(select(Refund)) if r.status in ("SENDING", "REQUESTED")
            )
            assert committed == reserved, "what is set aside is exactly what the live refunds hold"
            assert "FAILED" in statuses


def test_an_unknown_outcome_blocks_refunds_of_that_payment_even_when_requested_together():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider("ok", "timeout_after")
        payment_id = captured_payment(engine, provider)
        with Session(engine) as db:
            unknown = refund_job(provider, payment_id, "10.00")(db)
        assert unknown.status == "UNKNOWN_OUTCOME"
        calls = len(provider.calls)

        results = run_together(engine, [refund_job(provider, payment_id, "5.00")] * 4)

        assert all(isinstance(r, OutcomeUnknownBlockError) for r in results), results
        assert len(provider.calls) == calls and figures(engine, payment_id)[1] == Decimal(10)
