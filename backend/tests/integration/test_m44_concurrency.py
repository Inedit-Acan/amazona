"""Las carreras que M44 tiene que ganar, sobre PostgreSQL de verdad (Milestone 44, ADR 0024 y ADR 0028).

SQLite serializa todo y nunca reproduce una carrera: aquí cada hilo tiene su propia sesión o su propio cliente HTTP, en
una base PostgreSQL efímera, y arrancan juntos tras una barrera. La propiedad que importa no es «no falla»: es **el
estado persistente final**. Sea cual sea el orden en que se intercalen, el proveedor recibe como mucho una llamada por
operación, el dinero cobrado no se pierde ni se cuenta dos veces, nada queda a medias, y `check_invariants` se cumple.

Las que ya cubre su propio fichero (veinte pedidos con la misma clave, diez reembolsos, doce eventos iguales,
asignaciones, comprar contra cancelar) no se repiten: aquí están las que faltaban y una tormenta de operaciones
aleatorias concurrentes.
"""

import datetime
import random
import threading
from decimal import Decimal

from fulfilment_test_support import REQUESTER as FULFILMENT_REQUESTER
from fulfilment_test_support import ScriptedFulfilmentProvider, create_fulfillment, paid_order, service
from http_race_test_support import CLICKS, Api
from m44_invariants_test_support import check_invariants, provider_calls_never_exceed_the_frontier
from m44_walk_test_support import (
    OPERATIONS,
    SINGLE_THREAD_ONLY,
    STEPS,
    World,
    make_world,
    reconcile_events,
    resolve_by_hand,
    run_operation,
    sweep,
)
from order_test_support import add_product
from payment_test_support import (
    ScriptedPaymentProvider,
    add_order,
    ingress,
    run_together,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.core.errors import ConflictError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment, PaymentEvent
from app.money.money import Money
from app.orders.fulfilment_projection import fulfilment_reference
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED


def healthy(engine, *, calls: int | None = None) -> None:
    with Session(engine) as db:
        broken = check_invariants(db)
        if calls is not None:
            broken += provider_calls_never_exceed_the_frontier(db, calls)
    assert not broken, broken


def only_clean(results: list, *clean: type) -> list:
    """Nada de lo que devolvieron las tareas es una excepción que no sea una de las esperadas."""
    leaked = [r for r in results if isinstance(r, Exception) and not isinstance(r, clean)]
    assert not leaked, [f"{type(r).__name__}: {str(r)[:140]}" for r in leaked]
    return results


def capture_job(provider, payment_id: str, ref: str | None, event_id: str, amount: str = "50.00"):
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


# --- Cobros ---------------------------------------------------------------------------------------------------------


def test_twenty_clicks_to_open_a_payment_with_the_same_key_open_one_attempt():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                order = paid_unpaid_order(db)
            responses = api.together(
                lambda client, _: client.post(f"/api/orders/{order}/payments", headers={"Idempotency-Key": "pay-1"})
            )

            assert set(sorted(r.status_code for r in responses)) <= {201, 409}, [r.text[:120] for r in responses]
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(Payment)) == 1
                opened = db.scalars(select(ExternalAction).where(ExternalAction.operation == "payment.open")).all()
                assert len(opened) == 1 and opened[0].status == "SUCCEEDED", [a.status for a in opened]
            healthy(engine)
        finally:
            api.close()


def test_twenty_clicks_to_open_a_payment_with_different_keys_leave_one_live_attempt():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                order = paid_unpaid_order(db)
            responses = api.together(
                lambda client, i: client.post(f"/api/orders/{order}/payments", headers={"Idempotency-Key": f"pay-{i}"})
            )

            statuses = [r.status_code for r in responses]
            assert statuses.count(201) == 1 and statuses.count(409) == CLICKS - 1, sorted(statuses)
            with Session(engine) as db:
                live = db.scalars(
                    select(Payment).where(Payment.status.in_(("REQUESTED", "OPENING", "UNKNOWN_OUTCOME", "OPEN")))
                ).all()
                assert len(live) == 1, "at most one live attempt per order, even with twenty different intentions"
            healthy(engine)
        finally:
            api.close()


def paid_unpaid_order(db: Session) -> str:
    """Un pedido de 50.00 que espera el cobro."""
    return add_order(db, add_product(db)).id


def test_captures_of_different_orders_arriving_together_each_apply_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        jobs = []
        with Session(engine) as db:
            for index in range(12):
                payment = start_attempt(
                    db, add_order(db, add_product(db, name=f"P{index}"), customer=f"sim_c{index}"), provider
                )
                jobs.append(capture_job(provider, payment.id, payment.provider_payment_ref, f"evt_many_{index}"))

        results = only_clean(run_together(engine, jobs))

        assert all(r.outcome == "applied" and not r.duplicate for r in results)
        with Session(engine) as db:
            assert {o.status for o in db.scalars(select(Order))} == {"PAID"}
            assert db.scalar(select(func.sum(Payment.captured_amount))) == Decimal("600")
            assert {e.processing_status for e in db.scalars(select(PaymentEvent))} == {"APPLIED"}
        healthy(engine)


def test_a_capture_and_a_failure_of_the_same_payment_at_once_never_lose_the_money():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        for round_number in range(8):
            with Session(engine) as db:
                order = add_order(db, add_product(db, name=f"R{round_number}"), customer=f"sim_r{round_number}")
                payment = start_attempt(db, order, provider)
                payment_id, ref, order_id = payment.id, payment.provider_payment_ref, order.id
            failed_headers, failed_raw = provider.simulate_event(
                PaymentEventType.PAYMENT_FAILED,
                provider_payment_ref=ref,
                client_reference=payment_id,
                event_id=f"evt_fail_{round_number}",
            )

            def failure(session: Session, h=failed_headers, r=failed_raw):
                return ingress(session, provider).receive(provider.name, h, r)

            only_clean(
                run_together(engine, [capture_job(provider, payment_id, ref, f"evt_cap_{round_number}"), failure])
            )

            with Session(engine) as db:
                payment = db.get(Payment, payment_id)
                assert payment.status == "SUCCEEDED" and Decimal(str(payment.captured_amount)) == Decimal("50"), (
                    round_number,
                    payment.status,
                )
                assert db.get(Order, order_id).status == "PAID", "a capture is never discarded, whichever arrived first"
            healthy(engine)


def received_event(provider, engine, monkeypatch=None) -> tuple[str, str]:
    """Un evento verificado y guardado que **no se aplicó** (el proceso murió entre las dos transacciones)."""
    with Session(engine) as db:
        payment = start_attempt(db, add_order(db, add_product(db)), provider)
        headers, raw = provider.simulate_event(
            SUCCEEDED,
            provider_payment_ref=payment.provider_payment_ref,
            client_reference=payment.id,
            amount=Money.of("50.00", "EUR"),
            event_id="evt_received",
        )
        real_apply = PaymentService.apply

        def died(self, event_id):
            raise KeyboardInterrupt("died between the two transactions")

        PaymentService.apply = died  # type: ignore[method-assign]
        try:
            try:
                ingress(db, provider).receive(provider.name, headers, raw)
            except KeyboardInterrupt:
                pass
        finally:
            PaymentService.apply = real_apply  # type: ignore[method-assign]
        db.rollback()
        event = db.scalars(select(PaymentEvent)).one()
        assert event.processing_status == "RECEIVED"
        return event.id, payment.id


def test_two_workers_applying_the_same_received_event_apply_it_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        event_id, payment_id = received_event(provider, engine)

        results = only_clean(run_together(engine, [lambda s: PaymentService(s).apply(event_id)] * 6))

        assert {r.upper() for r in results} == {"APPLIED"}, "every worker is told the event's final state"
        with Session(engine) as db:
            effects = db.scalars(select(AuditLog).where(AuditLog.action == "payment.captured")).all()
            assert len(effects) == 1, "…but the capture was applied once: one audit, one amount"
            assert db.scalars(select(AuditLog).where(AuditLog.action == "payment_event.applied")).all().__len__() == 1
            payment = db.get(Payment, payment_id)
            assert payment.status == "SUCCEEDED" and Decimal(str(payment.captured_amount)) == Decimal("50")
            assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
            assert db.scalars(select(PaymentEvent)).one().processing_status == "APPLIED"
        healthy(engine)


def test_three_reconcilers_and_the_redelivery_apply_a_stuck_event_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        event_id, payment_id = received_event(provider, engine)
        with Session(engine) as db:
            db.execute(
                update(PaymentEvent).values(received_at=PaymentEvent.received_at - datetime.timedelta(minutes=10))
            )
            db.commit()
        from app.cli import reconcile_payment_events

        def reconcile(session: Session):
            return reconcile_payment_events(session, older_than_minutes=1)

        results = only_clean(run_together(engine, [reconcile, reconcile, reconcile]))

        assert all(isinstance(r, dict) for r in results), results
        with Session(engine) as db:
            assert len(db.scalars(select(AuditLog).where(AuditLog.action == "payment.captured")).all()) == 1
            assert Decimal(str(db.scalars(select(Payment)).one().captured_amount)) == Decimal("50")
            assert db.get(Payment, payment_id).status == "SUCCEEDED"
            assert db.scalars(select(PaymentEvent)).one().processing_status == "APPLIED"
        healthy(engine)


# --- Resultado desconocido: reconciliar, respuesta tardía y resolución humana
# ---------------------------------------------


def unknown_purchase(engine, provider) -> tuple[str, str]:
    """Una compra que el proveedor ejecutó y cuya respuesta se perdió: `UNKNOWN_OUTCOME`, con 29.00 de presupuesto
    apartado. Devuelve el fulfillment y la acción."""
    with Session(engine) as db:
        order = paid_order(db)
        BudgetLedgerService(db).authorise_budget(hard_limit=1000.0, actor="owner@amazona.local")
        fulfillment = create_fulfillment(db, order, provider)
        assert (
            service(db, provider).purchase(fulfillment.id, requester=FULFILMENT_REQUESTER).status == "UNKNOWN_OUTCOME"
        )
        action = db.scalars(
            select(ExternalAction).where(ExternalAction.reference == fulfilment_reference(fulfillment.id, "purchase"))
        ).one()
        return fulfillment.id, action.id


def test_reconciliation_the_late_response_and_a_person_cannot_all_close_the_same_unknown_outcome():
    with ephemeral_postgres() as engine:
        for round_number in range(4):
            provider = ScriptedFulfilmentProvider("timeout_after")
            fulfillment_id, action_id = unknown_purchase(engine, provider)

            def reconcile(session: Session):
                return ExternalActionService(session).reconcile(session.get(ExternalAction, action_id), provider, {})

            def late_response(session: Session):
                return ExternalActionService(session).finish(
                    session.get(ExternalAction, action_id),
                    ActionStatus.SUCCEEDED,
                    response=ActionResponse(reference="late_ref", detail={}),
                )

            def person(session: Session):
                return ExternalActionService(session).resolve(
                    session.get(ExternalAction, action_id),
                    succeeded=True,
                    actor="owner@amazona.local",
                    reason="seen in the portal",
                )

            only_clean(run_together(engine, [reconcile, late_response, person, reconcile]), Exception)

            with Session(engine) as db:
                fulfillment = db.get(Fulfillment, fulfillment_id)
                assert fulfillment.status == "PURCHASED" and fulfillment.unknown_phase is None, round_number
                assert db.get(ExternalAction, action_id).status == "SUCCEEDED"
                snapshot = BudgetLedgerService(db).snapshot()
                assert snapshot is not None
            healthy(engine)
            # El libro se movió una vez por cada compra cerrada, nunca dos veces por la misma.
            with Session(engine) as db:
                snapshot = BudgetLedgerService(db).snapshot()
                assert snapshot.reserved == 0.0 and snapshot.committed == 29.0 * (round_number + 1)


def test_two_workers_resuming_the_same_unknown_outcome_move_the_domain_and_the_ledger_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider("timeout_after")
        fulfillment_id, action_id = unknown_purchase(engine, provider)

        def reconcile(session: Session):
            return ExternalActionService(session).reconcile(session.get(ExternalAction, action_id), provider, {})

        results = only_clean(run_together(engine, [reconcile] * 6), Exception)

        assert [r for r in results if not isinstance(r, Exception)], "someone closed it"
        with Session(engine) as db:
            assert db.get(Fulfillment, fulfillment_id).status == "PURCHASED"
            snapshot = BudgetLedgerService(db).snapshot()
            assert snapshot is not None and snapshot.committed == 29.0 and snapshot.reserved == 0.0
            audits = [a for a in db.scalars(select(ExternalAction)) if a.reference.endswith(":purchase")]
            assert len(audits) == 1
        assert len(provider.calls) == 1, "the lookup asked; nobody executed the purchase again"
        healthy(engine, calls=len(provider.calls))


# --- Fulfillment -----------------------------------------------------------------------------------------------------


def purchased_fulfillment(engine, provider) -> str:
    with Session(engine) as db:
        order = paid_order(db)
        BudgetLedgerService(db).authorise_budget(hard_limit=1000.0, actor="owner@amazona.local")
        fulfillment = create_fulfillment(db, order, provider)
        service(db, provider).purchase(fulfillment.id, requester=FULFILMENT_REQUESTER)
        return fulfillment.id


def test_shipping_and_cancelling_at_once_never_give_back_a_bought_unit():
    with ephemeral_postgres() as engine:
        for _ in range(5):
            provider = ScriptedFulfilmentProvider()
            fulfillment_id = purchased_fulfillment(engine, provider)
            calls = len(provider.calls)

            def ship(session: Session):
                return service(session, provider).ship(fulfillment_id, requester=FULFILMENT_REQUESTER)

            def cancel(session: Session):
                return service(session, provider).cancel(fulfillment_id, actor="owner@amazona.local")

            results = only_clean(
                run_together(engine, [ship, cancel, cancel, fail_it(provider, fulfillment_id)]), ConflictError
            )

            assert any(not isinstance(r, Exception) and r.status == "SHIPPED" for r in results)
            assert len(provider.calls) == calls + 1, "the shipment went out once"
            with Session(engine) as db:
                assert db.get(Fulfillment, fulfillment_id).status == "SHIPPED"
                held = db.scalars(select(OrderItem).where(OrderItem.id.in_(select(OrderItem.id)))).all()
                assert all(item.allocated_quantity == item.quantity for item in held), (
                    "no bought unit returned to the pool"
                )
            healthy(engine, calls=len(provider.calls))


def fail_it(provider, fulfillment_id: str):
    def job(session: Session):
        return service(session, provider).fail(fulfillment_id, actor="owner@amazona.local")

    return job


def test_six_simultaneous_shipments_of_the_same_fulfillment_send_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedFulfilmentProvider()
        fulfillment_id = purchased_fulfillment(engine, provider)
        calls = len(provider.calls)

        results = only_clean(
            run_together(
                engine, [lambda s: service(s, provider).ship(fulfillment_id, requester=FULFILMENT_REQUESTER)] * 6
            ),
            ConflictError,
        )

        assert len([r for r in results if not isinstance(r, Exception)]) == 1
        assert len(provider.calls) == calls + 1
        with Session(engine) as db:
            ships = db.scalars(
                select(ExternalAction).where(ExternalAction.reference == fulfilment_reference(fulfillment_id, "ship"))
            ).all()
            assert len(ships) == 1 and ships[0].status == "SUCCEEDED"
        healthy(engine, calls=len(provider.calls))


def test_ten_purchases_over_http_with_different_keys_buy_once():
    with ephemeral_postgres() as engine:
        api = Api(engine)
        try:
            with Session(engine) as db:
                order = paid_order(db)
                fulfillment_id = create_fulfillment(db, order, ScriptedFulfilmentProvider()).id

            responses = api.together(
                lambda client, i: client.post(
                    f"/api/fulfillments/{fulfillment_id}/purchase", headers={"Idempotency-Key": f"buy-{i}"}
                ),
                count=10,
            )

            statuses = [r.status_code for r in responses]
            assert statuses.count(200) == 1 and set(statuses) <= {200, 409}, sorted(statuses)
            with Session(engine) as db:
                purchases = db.scalars(
                    select(ExternalAction).where(
                        ExternalAction.reference == fulfilment_reference(fulfillment_id, "purchase")
                    )
                ).all()
                assert len(purchases) == 1 and purchases[0].status == "SUCCEEDED"
                assert db.get(Fulfillment, fulfillment_id).status == "PURCHASED"
            healthy(engine)
        finally:
            api.close()


# --- La tormenta
# ---------------------------------------------------------------------------------------------------------


def test_a_storm_of_concurrent_random_operations_leaves_a_coherent_state_and_nothing_half_done():
    """Cinco hilos, cada uno con su semilla, hacen operaciones al azar contra la **misma** base PostgreSQL (la caminata
    de `m44_walk_test_support`, pero a la vez), con proveedores que fallan y procesos que mueren. Después, lo que
    existe (barrido, resolución humana, reconciliación de eventos) tiene que dejarlo todo cerrado. Si algún hilo
    recibe un error que no es una respuesta limpia —un interbloqueo, una violación de restricción— esta prueba lo
    dice."""
    for base_seed in (7, 8, 9, 10, 11, 12):
        with ephemeral_postgres() as engine:
            first, _ = make_world(base_seed * 100, engine)
            worlds = [first]
            for offset in range(1, 5):
                world = World(
                    factory=first.factory,
                    rnd=random.Random(base_seed * 100 + offset),
                    pay=first.pay,
                    ful=first.ful,
                    product=first.product,
                    quote=first.quote,
                )
                worlds.append(world)
            for world in worlds:
                world.sweep_after = datetime.timedelta(seconds=30)  # con hilos vivos, solo lo realmente huérfano
            allowed = [entry for entry in OPERATIONS if entry[1] not in SINGLE_THREAD_ONLY]
            weights = [weight for weight, _, _ in allowed]
            barrier = threading.Barrier(len(worlds))

            def storm(world: World) -> None:
                barrier.wait(timeout=30)
                for _ in range(STEPS):
                    _, name, operation = world.rnd.choices(allowed, weights=weights)[0]
                    world.log.append(name)
                    run_operation(world, name, operation)

            threads = [threading.Thread(target=storm, args=(w,)) for w in worlds]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=300)

            leaks = [leak for w in worlds for leak in w.leaks]
            assert not leaks, f"seed {base_seed}: {leaks[:5]}"
            calls = len(first.pay.calls) + len(first.ful.calls)
            healthy(engine, calls=calls)

            # La recuperación con lo que existe, ya sin hilos vivos: ahora el barrido puede ser total.
            worlds[0].sweep_after = datetime.timedelta(seconds=-1)
            run_operation(worlds[0], "reconcile_events", reconcile_events)
            run_operation(worlds[0], "sweep", sweep)
            for _ in range(80):
                with Session(engine) as db:
                    if (
                        db.scalar(select(ExternalAction.id).where(ExternalAction.status == "UNKNOWN_OUTCOME").limit(1))
                        is None
                    ):
                        break
                run_operation(worlds[0], "resolve_by_hand", resolve_by_hand)
            run_operation(worlds[0], "reconcile_events", reconcile_events)
            with Session(engine) as db:
                open_actions = [
                    a.reference
                    for a in db.scalars(select(ExternalAction))
                    if a.status in ("PENDING", "CALLING", "UNKNOWN_OUTCOME")
                ]
                stuck_events = db.scalar(
                    select(func.count()).select_from(PaymentEvent).where(PaymentEvent.processing_status == "RECEIVED")
                )
            assert not open_actions and not stuck_events, f"seed {base_seed}: {open_actions} / {stuck_events} events"
            healthy(engine, calls=len(first.pay.calls) + len(first.ful.calls))
