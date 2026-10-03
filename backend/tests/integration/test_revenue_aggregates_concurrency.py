"""Las lecturas de agregados mientras se escribe, con carreras reales (Milestone 45, ADR 0030).

Lectores que consultan sin parar el resumen, la serie y las páginas mientras llega una tormenta de capturas y
reembolsos en una base PostgreSQL efímera. Lo que se afirma son invariantes, no tiempos: **ninguna lectura falla ni
se contradice** (el neto es ingreso menos reembolso, lo pendiente es lo recibido menos lo devuelto), una página
nunca repite una entrada, y cuando todo termina el resumen cuadra con el estado de los cobros. Leer no bloquea a
quien escribe.
"""

import datetime
import threading
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
from revenue_test_support import confirm_refund
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.order import Order
from app.db.models.payment import Payment
from app.money.money import Money
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType
from app.revenue import aggregates
from app.revenue.aggregates import Period

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
EXPIRED = PaymentEventType.PAYMENT_EXPIRED
ORDERS = 10


def capture(provider, payment_id: str, ref: str | None, event_id: str):
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=ref,
        client_reference=payment_id,
        amount=Money.of("50.00", "EUR"),
        event_id=event_id,
    )

    def job(session: Session):
        return ingress(session, provider).receive(provider.name, headers, raw)

    return job


def consistent(result: dict) -> None:
    for row in result["verified"]:
        assert Decimal(row["net"]) == Decimal(row["revenue"]) - Decimal(row["refunds"]), row
    for row in result["under_review"]:
        assert Decimal(row["outstanding"]) == Decimal(row["received"]) - Decimal(row["refunded"]), row


def test_readers_during_a_storm_of_writes_never_fail_or_contradict_themselves_and_the_end_matches_the_payments():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        with Session(engine) as db:
            targets = []
            for number in range(ORDERS):
                order = add_order(db, add_product(db, name=f"Widget {number}"), customer=f"sim_{number}")
                first = start_attempt(db, db.get(Order, order.id), provider)
                deliver(db, provider, EXPIRED, first)
                second = start_attempt(db, db.get(Order, order.id), provider)
                targets.append(((first.id, first.provider_payment_ref), (second.id, second.provider_payment_ref)))

        stop = threading.Event()
        failures: list[BaseException] = []
        reads = [0]

        def reader() -> None:
            try:
                with Session(engine) as session:
                    while not stop.is_set():
                        consistent(aggregates.summary(session, Period()))
                        session.rollback()
                        page = aggregates.entries_page(session, period=Period(), limit=7)
                        ids = [entry.id for entry in page.entries]
                        assert len(ids) == len(set(ids)), "a page never repeats an entry"
                        now = datetime.datetime.now(datetime.UTC)
                        aggregates.series(
                            session,
                            granularity="day",
                            period=aggregates.resolve_series_period("day", Period(), now=now),
                        )
                        session.rollback()
                        reads[0] += 1
            except BaseException as exc:  # noqa: BLE001 - se recoge para afirmarlo desde el hilo principal
                failures.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(3)]
        for thread in readers:
            thread.start()
        try:
            jobs = []
            for number, (first, second) in enumerate(targets):
                jobs.append(capture(provider, first[0], first[1], f"evt_f{number}"))
                jobs.append(capture(provider, second[0], second[1], f"evt_s{number}"))
            results = run_together(engine, jobs)
        finally:
            stop.set()
            for thread in readers:
                thread.join(timeout=30)

        assert not failures, failures
        assert not [r for r in results if isinstance(r, Exception)], results
        assert reads[0] > 0, "the readers did run while the writes were happening"

        with Session(engine) as db:
            refunds = [
                RefundService(db, settings=SIMULATION, provider=provider).request(
                    p.id, amount=Money.of("50.00", "EUR"), reason="duplicate_capture", requester=REQUESTER
                )
                for p in db.scalars(select(Payment).where(Payment.status == "DUPLICATE_CAPTURE"))
            ]
            for refund in refunds:
                confirm_refund(db, provider, refund)

            result = aggregates.summary(db, Period())
            consistent(result)
            canonical = db.scalar(select(func.sum(Payment.captured_amount)).where(Payment.status == "SUCCEEDED"))
            verified = next(r for r in result["verified"] if r["currency"] == "EUR")
            assert Decimal(verified["revenue"]) == Decimal(str(canonical)) == Decimal(ORDERS * 50)
            duplicate = next(r for r in result["under_review"] if r["classification"] == "DUPLICATE_RECEIPT")
            assert Decimal(duplicate["received"]) == Decimal(ORDERS * 50)
            assert Decimal(duplicate["refunded"]) == Decimal(ORDERS * 50) and Decimal(duplicate["outstanding"]) == 0
            assert Decimal(verified["refunds"]) == 0, "refunding the duplicates never touches the legitimate revenue"
