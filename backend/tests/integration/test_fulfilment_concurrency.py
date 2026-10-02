"""El fulfillment con carreras reales (Milestone 44, ADR 0028 §6).

SQLite serializa las transacciones y nunca reproduce una carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el
orden en que se intercalen, **jamás se asigna más de lo que tiene una línea**, **jamás se compra algo cuyas unidades
volvieron al pool** (ni se devuelven unidades de algo que se compró), y una misma operación se pide una vez.
"""

import threading
import time

from fulfilment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedFulfilmentProvider,
    paid_order,
)
from payment_test_support import run_together
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment, FulfillmentItem
from app.db.models.order import OrderItem
from app.orders.errors import OutcomeUnknownBlockError
from app.orders.fulfilment import FulfilmentRequestLine, FulfilmentService

ROUNDS = 12


def service(session: Session, provider: ScriptedFulfilmentProvider) -> FulfilmentService:
    return FulfilmentService(session, settings=SIMULATION, provider=provider)


def order_with_lines(engine, customer: str = "sim_customer") -> tuple[str, list[str]]:
    with Session(engine) as db:
        order = paid_order(db, customer=customer)
        ids = [
            i.id
            for i in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.line_number))
        ]
        return order.id, ids


def allocated(engine, order_id: str) -> list[int]:
    with Session(engine) as db:
        return [
            i.allocated_quantity
            for i in db.scalars(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.line_number))
        ]


def assigned_in_fulfillments(engine, order_id: str) -> list[int]:
    """Lo que dicen los fulfillments que **siguen reclamando** unidades, línea a línea: debe ser igual a lo asignado."""
    live = ("READY", "PURCHASING", "PURCHASED", "SHIPPING", "SHIPPED", "COMPLETED", "UNKNOWN_OUTCOME")
    with Session(engine) as db:
        totals: list[int] = []
        for item in db.scalars(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.line_number)):
            total = db.scalar(
                select(func.coalesce(func.sum(FulfillmentItem.quantity), 0))
                .join(Fulfillment, Fulfillment.id == FulfillmentItem.fulfillment_id)
                .where(FulfillmentItem.order_item_id == item.id, Fulfillment.status.in_(live))
            )
            totals.append(int(total or 0))
        return totals


def create_job(order_id: str, provider, quantities: dict[str, int]):
    def job(session: Session):
        lines = [FulfilmentRequestLine(item_id, q) for item_id, q in quantities.items()]
        return service(session, provider).create(order_id, lines, actor="owner@amazona.local")

    return job


def calls_for(engine, fulfillment_id: str, phase: str) -> int:
    with Session(engine) as db:
        return (
            db.scalar(
                select(func.count())
                .select_from(ExternalAction)
                .where(ExternalAction.reference == f"order_fulfilment:{fulfillment_id}:{phase}")
            )
            or 0
        )


# --- Asignación ----------------------------------------------------------------------------------------------------


def test_ten_simultaneous_assignments_never_assign_more_than_the_line_has():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, _) = order_with_lines(engine)

        results = run_together(engine, [create_job(order_id, provider, {first: 1})] * 10)

        done = [r for r in results if isinstance(r, Fulfillment)]
        refused = [r for r in results if isinstance(r, ConflictError)]
        assert len(done) == 4 and len(refused) == 6, [type(r).__name__ for r in results]
        assert allocated(engine, order_id) == [4, 0]
        assert assigned_in_fulfillments(engine, order_id) == [4, 0], "what is assigned is what the fulfillments hold"
        with Session(engine) as db:
            assert len(db.scalars(select(Fulfillment)).all()) == 4, "a refused request leaves nothing behind"


def test_two_requests_that_do_not_fit_together_leave_exactly_one_and_never_half_of_either():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, second) = order_with_lines(engine)

        results = run_together(
            engine,
            [
                create_job(order_id, provider, {first: 3, second: 2}),
                create_job(order_id, provider, {first: 2, second: 2}),
            ],
        )

        assert sorted(type(r).__name__ for r in results) == ["ConflictError", "Fulfillment"], results
        assert allocated(engine, order_id) in ([3, 2], [2, 2]), "all or nothing, even when they race"
        assert assigned_in_fulfillments(engine, order_id) == allocated(engine, order_id)


def test_lines_competed_for_in_opposite_order_do_not_deadlock():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, second) = order_with_lines(engine)
        forward = create_job(order_id, provider, {first: 2, second: 1})
        backward = create_job(order_id, provider, {second: 1, first: 2})

        results = run_together(engine, [forward, backward, forward, backward])

        assert not [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)], results
        assert len([r for r in results if isinstance(r, Fulfillment)]) == 2
        assert allocated(engine, order_id) == [4, 2] == assigned_in_fulfillments(engine, order_id)


# --- Comprar contra cancelar -----------------------------------------------------------------------------------------


def test_buying_and_cancelling_at_once_never_both_win():
    with ephemeral_postgres() as engine:
        outcomes = {"bought": 0, "cancelled": 0}
        for round_number in range(ROUNDS):
            provider = ScriptedFulfilmentProvider()
            order_id, (first, _) = order_with_lines(engine, customer=f"sim_race_{round_number}")
            with Session(engine) as db:
                fulfillment_id = (
                    service(db, provider)
                    .create(order_id, [FulfilmentRequestLine(first, 4)], actor="owner@amazona.local")
                    .id
                )

            def buy(session: Session, fid=fulfillment_id, p=provider):
                return service(session, p).purchase(fid, requester=REQUESTER)

            def cancel(session: Session, fid=fulfillment_id, p=provider, delay=round_number * 0.012):
                time.sleep(delay)  # de «cancelar primero» a «cancelar cuando la compra ya salió»
                return service(session, p).cancel(fid, actor="owner@amazona.local")

            results = run_together(engine, [buy, cancel])

            with Session(engine) as db:
                final = db.get(Fulfillment, fulfillment_id)
                assert final is not None
                held = allocated(engine, order_id)[0]
            went_out = len(provider.calls)
            assert final.status in ("PURCHASED", "CANCELLED"), (final.status, results)
            if final.status == "PURCHASED":
                outcomes["bought"] += 1
                assert went_out == 1 and held == 4, "bought: the provider was asked once and the units stay assigned"
                assert any(isinstance(r, ConflictError) for r in results), "the cancellation was refused"
            else:
                outcomes["cancelled"] += 1
                assert went_out == 0 and held == 0, "cancelled: nothing was bought and the units went back"
                assert any(isinstance(r, Exception) for r in results), "the purchase did not go out"
            assert assigned_in_fulfillments(engine, order_id)[0] == held
            assert calls_for(engine, fulfillment_id, "purchase") <= 1
        assert sum(outcomes.values()) == ROUNDS
        assert outcomes["bought"] and outcomes["cancelled"], f"the staggered race must reach both sides: {outcomes}"


class HeldProvider(ScriptedFulfilmentProvider):
    """Retiene la llamada en pleno vuelo hasta que la prueba la suelta: la petición **pudo salir**."""

    def __init__(self) -> None:
        super().__init__()
        self.in_flight = threading.Event()
        self.release = threading.Event()

    def execute(self, request):
        self.in_flight.set()
        assert self.release.wait(timeout=20), "the test never released the call"
        return super().execute(request)


def test_a_cancellation_while_the_purchase_is_in_flight_is_refused_and_keeps_the_units():
    with ephemeral_postgres() as engine:
        provider = HeldProvider()
        order_id, (first, _) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = (
                service(db, provider)
                .create(order_id, [FulfilmentRequestLine(first, 4)], actor="owner@amazona.local")
                .id
            )
        outcome: list = []

        def buy() -> None:
            with Session(engine) as session:
                outcome.append(service(session, provider).purchase(fulfillment_id, requester=REQUESTER))

        thread = threading.Thread(target=buy)
        thread.start()
        try:
            assert provider.in_flight.wait(timeout=20), "the purchase never reached the provider"
            with Session(engine) as db:
                assert db.get(Fulfillment, fulfillment_id).status == "PURCHASING"  # type: ignore[union-attr]
                for attempt in (
                    lambda: service(db, provider).cancel(fulfillment_id, actor="owner"),
                    lambda: service(db, provider).fail(fulfillment_id, actor="owner"),
                ):
                    try:
                        attempt()
                    except ConflictError:
                        pass
                    else:
                        raise AssertionError("a request that may already be out cannot give its units back")
            assert allocated(engine, order_id) == [4, 0]
        finally:
            provider.release.set()
            thread.join(timeout=30)

        assert outcome and outcome[0].status == "PURCHASED"
        assert allocated(engine, order_id) == [4, 0] == assigned_in_fulfillments(engine, order_id)


def test_a_cancellation_that_loses_to_a_purchase_cannot_give_the_units_back_later():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, _) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = (
                service(db, provider)
                .create(order_id, [FulfilmentRequestLine(first, 4)], actor="owner@amazona.local")
                .id
            )
            service(db, provider).purchase(fulfillment_id, requester=REQUESTER)

        results = run_together(
            engine,
            [lambda s: service(s, provider).cancel(fulfillment_id, actor="a")] * 4
            + [lambda s: service(s, provider).fail(fulfillment_id, actor="a")] * 2,
        )

        assert all(isinstance(r, ConflictError) for r in results), results
        assert allocated(engine, order_id) == [4, 0]
        with Session(engine) as db:
            assert db.get(Fulfillment, fulfillment_id).status == "PURCHASED"  # type: ignore[union-attr]


def test_a_purchase_that_may_have_bought_blocks_a_simultaneous_cancellation_too():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider("timeout_after")
        order_id, (first, _) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = (
                service(db, provider)
                .create(order_id, [FulfilmentRequestLine(first, 4)], actor="owner@amazona.local")
                .id
            )
            assert service(db, provider).purchase(fulfillment_id, requester=REQUESTER).status == "UNKNOWN_OUTCOME"

        results = run_together(engine, [lambda s: service(s, provider).cancel(fulfillment_id, actor="a")] * 3)

        assert all(isinstance(r, OutcomeUnknownBlockError) for r in results), results
        assert allocated(engine, order_id) == [4, 0]


# --- Operaciones repetidas ----------------------------------------------------------------------------------------


def test_six_simultaneous_purchases_of_the_same_fulfillment_ask_the_provider_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, second) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = (
                service(db, provider)
                .create(order_id, [FulfilmentRequestLine(first, 4), FulfilmentRequestLine(second, 2)], actor="o")
                .id
            )

        results = run_together(
            engine, [lambda s: service(s, provider).purchase(fulfillment_id, requester=REQUESTER)] * 6
        )

        done = [r for r in results if isinstance(r, Fulfillment)]
        refused = [r for r in results if isinstance(r, ConflictError)]
        assert len(done) == 1 and len(refused) == 5, [type(r).__name__ for r in results]
        assert len(provider.calls) == 1, "one purchase went out, not six"
        assert calls_for(engine, fulfillment_id, "purchase") == 1


def test_simultaneous_cancellations_release_the_units_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, _) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = service(db, provider).create(order_id, [FulfilmentRequestLine(first, 3)], actor="o").id
            other = service(db, provider).create(order_id, [FulfilmentRequestLine(first, 1)], actor="o").id

        results = run_together(engine, [lambda s: service(s, provider).cancel(fulfillment_id, actor="a")] * 6)

        assert len([r for r in results if isinstance(r, Fulfillment)]) == 1
        assert all(isinstance(r, ConflictError) for r in results if not isinstance(r, Fulfillment)), results
        assert allocated(engine, order_id) == [1, 0], "three units went back once, not six times (and not below zero)"
        with Session(engine) as db:
            assert db.get(Fulfillment, other).status == "READY"  # type: ignore[union-attr]


def test_simultaneous_deliveries_close_the_order_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        order_id, (first, second) = order_with_lines(engine)
        with Session(engine) as db:
            fulfillment_id = (
                service(db, provider)
                .create(order_id, [FulfilmentRequestLine(first, 4), FulfilmentRequestLine(second, 2)], actor="o")
                .id
            )
            service(db, provider).purchase(fulfillment_id, requester=REQUESTER)
            service(db, provider).ship(fulfillment_id, requester=REQUESTER)

        results = run_together(engine, [lambda s: service(s, provider).complete(fulfillment_id, actor="owner")] * 5)

        assert len([r for r in results if isinstance(r, Fulfillment)]) == 1, [type(r).__name__ for r in results]
        assert all(isinstance(r, ConflictError) for r in results if not isinstance(r, Fulfillment))
        with Session(engine) as db:
            from app.db.models.audit import AuditLog
            from app.db.models.order import Order

            assert db.get(Order, order_id).status == "COMPLETED"  # type: ignore[union-attr]
            closed = db.scalars(select(AuditLog).where(AuditLog.action == "order.completed")).all()
            assert len(closed) == 1, "the order was closed once"
