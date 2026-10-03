"""El registro de ingresos verificados, con carreras reales (Milestone 45, ADR 0030 §7 y §9).

SQLite serializa las transacciones y nunca reproduce una carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el
orden en que se intercalen, hay **una** entrada por hecho, ninguna entrada huérfana de una captura que perdió la
carrera, y el registro cuadra con el estado de los cobros.
"""

import datetime
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

from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.money.money import Money
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService
from app.revenue.check import check_ledger

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
EXPIRED = PaymentEventType.PAYMENT_EXPIRED
REFUND_SUCCEEDED = PaymentEventType.REFUND_SUCCEEDED


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


def errors(results: list) -> list[Exception]:
    return [r for r in results if isinstance(r, Exception)]


def new_order_id(engine) -> str:
    with Session(engine) as db:
        return add_order(db, add_product(db)).id


def kinds(db: Session) -> list[tuple[str, str]]:
    return sorted((e.kind, e.classification) for e in db.scalars(select(RevenueLedgerEntry)).all())


def assert_ledger_matches_payments(db: Session) -> None:
    status = check_ledger(db)
    assert status["divergences"]["count"] == 0, status["divergences"]
    assert status["outside_ledger"]["count"] == 0, status["outside_ledger"]
    captured = db.scalar(select(func.sum(Payment.captured_amount))) or 0
    projected = db.scalar(select(func.sum(RevenueLedgerEntry.amount)).where(RevenueLedgerEntry.kind == "CAPTURE")) or 0
    assert Decimal(str(captured)) == Decimal(str(projected))


def test_two_attempts_captured_at_once_leave_one_order_payment_and_one_duplicate_receipt_and_no_orphan():
    """La carrera del índice: la que pierde se reescribe como duplicado, y su entrada con ella, nunca huérfana."""
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = new_order_id(engine)
        with Session(engine) as db:
            order = db.get(Order, order_id)
            first = start_attempt(db, order, provider)
            deliver(db, provider, EXPIRED, first)
            second = start_attempt(db, order, provider)
            ids = [(first.id, first.provider_payment_ref), (second.id, second.provider_payment_ref)]

        results = run_together(
            engine,
            [capture(provider, pid, ref, f"evt_{n}") for n, (pid, ref) in enumerate(ids)],
        )

        assert not errors(results), errors(results)
        with Session(engine) as db:
            assert kinds(db) == [("CAPTURE", "DUPLICATE_RECEIPT"), ("CAPTURE", "ORDER_PAYMENT")]
            by_payment = {e.payment_id: e for e in db.scalars(select(RevenueLedgerEntry))}
            for payment in db.scalars(select(Payment).where(Payment.order_id == order_id)):
                if Decimal(str(payment.captured_amount)) > 0:
                    assert by_payment[payment.id].amount == Decimal(str(payment.captured_amount))
                    expected = "ORDER_PAYMENT" if payment.status == "SUCCEEDED" else "DUPLICATE_RECEIPT"
                    assert by_payment[payment.id].classification == expected
                else:
                    assert payment.id not in by_payment, "an entry for a capture that does not exist"
            assert_ledger_matches_payments(db)


def test_the_same_capture_delivered_twelve_times_at_once_is_one_entry():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = new_order_id(engine)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            payment_id, ref = payment.id, payment.provider_payment_ref

        results = run_together(engine, [capture(provider, payment_id, ref, "evt_same")] * 12)

        assert not errors(results), errors(results)
        with Session(engine) as db:
            assert kinds(db) == [("CAPTURE", "ORDER_PAYMENT")]
            assert_ledger_matches_payments(db)


def test_two_different_capture_events_for_one_payment_leave_one_entry():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = new_order_id(engine)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            payment_id, ref = payment.id, payment.provider_payment_ref

        results = run_together(
            engine, [capture(provider, payment_id, ref, "evt_a"), capture(provider, payment_id, ref, "evt_b")]
        )

        assert not errors(results), errors(results)
        assert sorted(r.outcome for r in results) == ["applied", "stale"]
        with Session(engine) as db:
            assert kinds(db) == [("CAPTURE", "ORDER_PAYMENT")]
            assert_ledger_matches_payments(db)


def test_one_stored_event_applied_by_many_workers_at_once_is_one_entry():
    """Lo que hacen a la vez la reentrega del proveedor, el reconciliador programado y `retry-payment-event`."""
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = new_order_id(engine)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            headers, raw = provider.simulate_event(
                SUCCEEDED,
                provider_payment_ref=payment.provider_payment_ref,
                client_reference=payment.id,
                amount=Money.of("50.00", "EUR"),
                event_id="evt_stored",
            )
            verified = provider.verify_webhook(headers=headers, raw_body=raw, now=datetime.datetime.now(datetime.UTC))
            event_id, _ = ingress(db, provider)._record(verified)

        def apply(session: Session):
            return PaymentService(session).apply(event_id)

        results = run_together(engine, [apply] * 10)

        assert not errors(results), errors(results)
        assert sorted(set(results)) == ["APPLIED"]
        with Session(engine) as db:
            assert kinds(db) == [("CAPTURE", "ORDER_PAYMENT")]
            assert db.get(PaymentEvent, event_id).processing_status == "APPLIED"


def test_the_same_refund_confirmation_delivered_at_once_is_one_refund_entry():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        order_id = new_order_id(engine)
        with Session(engine) as db:
            payment = start_attempt(db, db.get(Order, order_id), provider)
            deliver(db, provider, SUCCEEDED, payment)
            refund = RefundService(db, settings=SIMULATION, provider=provider).request(
                payment.id, amount=Money.of("20.00", "EUR"), reason="customer_request", requester=REQUESTER
            )
            headers, raw = provider.simulate_event(
                REFUND_SUCCEEDED,
                provider_payment_ref=payment.provider_payment_ref,
                provider_refund_ref=refund.provider_refund_ref,
                client_reference=refund.id,
                amount=Money.of("20.00", "EUR"),
                event_id="evt_refund_same",
            )

        def confirm(session: Session):
            return ingress(session, provider).receive(provider.name, headers, raw)

        results = run_together(engine, [confirm] * 12)

        assert not errors(results), errors(results)
        with Session(engine) as db:
            assert kinds(db) == [("CAPTURE", "ORDER_PAYMENT"), ("REFUND", "ORDER_PAYMENT")]
            assert Decimal(str(db.scalars(select(Payment)).one().refunded_amount)) == Decimal("20")
            assert db.scalars(select(Refund)).one().status == "SUCCEEDED"
            assert_ledger_matches_payments(db)
            assert check_ledger(db)["divergences"]["count"] == 0


def test_a_mixed_storm_of_captures_duplicates_and_refunds_leaves_the_ledger_matching_the_payments():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        with Session(engine) as db:
            orders = [add_order(db, add_product(db, name=f"Widget {n}"), customer=f"sim_{n}") for n in range(4)]
            targets = []
            for order in orders:
                first = start_attempt(db, order, provider)
                deliver(db, provider, EXPIRED, first)
                second = start_attempt(db, order, provider)
                targets.append(((first.id, first.provider_payment_ref), (second.id, second.provider_payment_ref)))

        jobs = []
        for number, (first, second) in enumerate(targets):
            jobs.append(capture(provider, first[0], first[1], f"evt_f{number}"))
            redelivered = capture(provider, second[0], second[1], f"evt_s{number}")
            jobs.extend([redelivered, redelivered])  # el mismo mensaje firmado, entregado dos veces
        results = run_together(engine, jobs)

        assert not errors(results), errors(results)
        with Session(engine) as db:
            assert kinds(db).count(("CAPTURE", "ORDER_PAYMENT")) == 4
            assert kinds(db).count(("CAPTURE", "DUPLICATE_RECEIPT")) == 4
            assert len(kinds(db)) == 8
            assert_ledger_matches_payments(db)

            duplicates = list(db.scalars(select(Payment).where(Payment.status == "DUPLICATE_CAPTURE")))
            refunds = [
                RefundService(db, settings=SIMULATION, provider=provider).request(
                    p.id, amount=Money.of("50.00", "EUR"), reason="duplicate_capture", requester=REQUESTER
                )
                for p in duplicates
            ]
            confirmations = []
            for refund in refunds:
                payment = db.get(Payment, refund.payment_id)
                headers, raw = provider.simulate_event(
                    REFUND_SUCCEEDED,
                    provider_payment_ref=payment.provider_payment_ref,
                    provider_refund_ref=refund.provider_refund_ref,
                    client_reference=refund.id,
                    amount=Money.of("50.00", "EUR"),
                    event_id=f"evt_ref_{refund.id}",
                )
                for _ in range(2):  # y cada confirmación llega dos veces a la vez
                    confirmations.append((headers, raw))

        def confirm(pair):
            def job(session: Session):
                return ingress(session, provider).receive(provider.name, pair[0], pair[1])

            return job

        results = run_together(engine, [confirm(pair) for pair in confirmations])

        assert not errors(results), errors(results)
        with Session(engine) as db:
            refund_rows = list(db.scalars(select(RevenueLedgerEntry).where(RevenueLedgerEntry.kind == "REFUND")))
            assert len(refund_rows) == 4
            assert {r.classification for r in refund_rows} == {"DUPLICATE_RECEIPT"}, "never the legitimate revenue"
            assert_ledger_matches_payments(db)
            assert check_ledger(db)["divergences"]["count"] == 0
