"""Caos de M45 que ninguna prueba anterior hacía con el registro de ingresos delante (Milestone 45, ADR 0029 y 0030).

M44 y los commits de M45 ya cubren, cada uno en su fichero, la mayoría de los fallos que importan: la caída antes y
después de `begin_call`, la respuesta tardía, dos workers sobre la misma operación, el webhook repetido, el mismo id con
otro contenido, el reembolso concurrente, comprar contra cancelar, el reconciliador a la vez que una reentrega.
**No se repiten.** El mapa de qué prueba cubre qué está en `test_m45_coverage_map.py`, y ese test falla si alguna de
esas pruebas desaparece o cambia de nombre.

Lo que faltaba, y está aquí, es lo que solo se ve **con el dinero verificado bajo la lupa**:

1. **Un lease vencido en el trabajo de reconciliación**: el worker A reclama el tick y muere; el B lo recupera y
   aplica el evento; el A, zombi, intenta cerrar el trabajo. El dinero se cuenta **una** vez.
2. **Eventos fuera de orden**: un reembolso del proveedor que llega **antes** que su cobro, en todos los órdenes
   posibles. El ingreso verificado es el mismo en todos; lo que no cabe queda como evidencia visible y **no** como una
   entrada inventada.
3. **Una tormenta concurrente con el oráculo del registro** (la de M44 solo miraba los invariantes de M44): cinco hilos,
   un PostgreSQL, y al final, y tras recuperar, el registro cuadra con los cobros y no se ha reescrito nada.
4. **La reconciliación no reinterpreta un resultado desconocido**, ni con la edad que se le dé: sean cuales sean las
   pasadas, el estado y el dinero reservado no cambian.

Todas las carreras usan barreras explícitas y un PostgreSQL efímero; ninguna es probabilística.
"""

import datetime
import itertools
import random
import threading
from decimal import Decimal

import pytest
from m44_invariants_test_support import check_invariants
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
from m45_invariants_test_support import LedgerWatch, check_revenue_invariants
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    ingress,
    reload,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.external_action import ExternalAction
from app.db.models.job import JobEvent
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry
from app.jobs.handlers import RECONCILE_PAYMENT_EVENTS
from app.jobs.queue import JobQueue
from app.jobs.schemas import JobStatus
from app.jobs.worker import Worker
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService
from app.reconciliation.actions import ActionReconciler
from app.reconciliation.events import EventReconciler

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
REFUND_SUCCEEDED = PaymentEventType.REFUND_SUCCEEDED
QUIET_WORKER = Settings(_env_file=None, reconciliation_enabled=False)


def _entries(db: Session) -> list[RevenueLedgerEntry]:
    db.expire_all()
    return list(db.scalars(select(RevenueLedgerEntry)))


def _signed(provider: ScriptedPaymentProvider, kind: PaymentEventType, payment: Payment, **kwargs):
    """Los bytes firmados de un evento, **una sola vez**: reentregarlo es enviar exactamente estos mismos bytes. (Firmar
    otra vez con el mismo id es otro instante, y eso es un conflicto, no una reentrega.)"""
    money = Money.of(kwargs.pop("amount", str(payment.amount)), payment.currency)
    return provider.simulate_event(
        kind,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=money,
        **kwargs,
    )


def _stored_but_not_applied(db: Session, provider: ScriptedPaymentProvider, payment: Payment):
    """Un proceso que muere entre guardar el evento verificado y aplicarlo: el evento queda `RECEIVED` y viejo.
    Devuelve el evento y los bytes firmados que llegaron (para poder reentregarlos tal cual)."""
    signed = _signed(provider, SUCCEEDED, payment)
    real_apply = PaymentService.apply

    def died(self, event_id):
        raise KeyboardInterrupt("the process died between storing the event and applying it")

    PaymentService.apply = died  # type: ignore[method-assign]
    try:
        with pytest.raises(KeyboardInterrupt):
            ingress(db, provider).receive(provider.name, *signed)
    finally:
        PaymentService.apply = real_apply  # type: ignore[method-assign]
    db.rollback()
    stored = db.scalars(select(PaymentEvent).where(PaymentEvent.processing_status == "RECEIVED")).one()
    stored.received_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30)
    db.commit()
    return stored, signed


# --- 1 · Un lease vencido en el trabajo de reconciliación -------------------------------------------------------


def test_a_worker_that_dies_holding_the_reconciliation_tick_is_replaced_and_the_money_counts_once():
    with ephemeral_postgres() as engine:
        factory = session_factory(engine)
        provider = ScriptedPaymentProvider()
        with factory() as db:
            product = add_product(db)
            payment = start_attempt(db, add_order(db, product, price="25.00", quantity=2), provider)
            stored, _ = _stored_but_not_applied(db, provider, payment)
            stored_id, payment_id = stored.id, payment.id

        # El worker A reclama el tick y muere sin cerrarlo: su arriendo caduca.
        with factory() as db:
            queue = JobQueue(db)
            job = queue.enqueue(job_type=RECONCILE_PAYMENT_EVENTS, max_attempts=3)
            job_id = job.id
            claimed = queue.claim(worker="worker-A-that-died", lease_seconds=60)
            assert claimed is not None and claimed.id == job_id
            claimed.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
            db.commit()

        # El worker B recupera el arriendo vencido en su vuelta y hace el trabajo.
        with factory() as db:
            handled = Worker(name="worker-B", settings=QUIET_WORKER).run_once(db)
            assert handled is not None and handled.id == job_id

        with factory() as db:
            event = db.get(PaymentEvent, stored_id)
            assert event.processing_status == "APPLIED" and event.reconcile_attempts == 1
            assert db.get(Payment, payment_id).status == "SUCCEEDED"
            kinds = [e.kind for e in db.query(JobEvent).filter_by(job_id=job_id).all()]
            assert "lease_expired" in kinds
            assert db.get(type(job), job_id).status == JobStatus.COMPLETED
            assert len(_entries(db)) == 1
            assert check_invariants(db) == [] and check_revenue_invariants(db) == []

        # El worker A, zombi, despierta e intenta cerrar lo que ya no es suyo: no puede, y nada se mueve.
        with factory() as db:
            with pytest.raises(Exception) as refused:  # noqa: PT011 - el tipo es del runtime de trabajos
                JobQueue(db).complete(job_id, worker="worker-A-that-died")
            assert "held" in str(refused.value).lower() or "worker" in str(refused.value).lower()
            db.rollback()

        # Otras dos vueltas del mismo tick no encuentran nada que aplicar: el dinero no se cuenta otra vez.
        for _ in range(2):
            with factory() as db:
                JobQueue(db).enqueue(job_type=RECONCILE_PAYMENT_EVENTS, max_attempts=3)
            with factory() as db:
                Worker(name="worker-B", settings=QUIET_WORKER).run_once(db)
        with factory() as db:
            assert len(_entries(db)) == 1
            assert db.get(PaymentEvent, stored_id).reconcile_attempts == 1, "the attempt was counted once"
            assert check_revenue_invariants(db) == []


def test_two_workers_taking_the_same_tick_at_once_apply_the_stored_event_once():
    with ephemeral_postgres() as engine:
        factory = session_factory(engine)
        provider = ScriptedPaymentProvider()
        with factory() as db:
            product = add_product(db)
            payment = start_attempt(db, add_order(db, product, price="10.00", quantity=3), provider)
            _stored_but_not_applied(db, provider, payment)
        with factory() as db:
            for _ in range(2):
                JobQueue(db).enqueue(job_type=RECONCILE_PAYMENT_EVENTS, max_attempts=3)

        barrier = threading.Barrier(2)
        failures: list[BaseException] = []

        def work(name: str) -> None:
            try:
                barrier.wait(timeout=30)
                with factory() as db:
                    Worker(name=name, settings=QUIET_WORKER).run_once(db)
            except BaseException as exc:  # noqa: BLE001 - lo que escapa es el hallazgo
                failures.append(exc)

        threads = [threading.Thread(target=work, args=(f"worker-{n}",)) for n in "AB"]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert failures == []
        with factory() as db:
            assert len(_entries(db)) == 1
            assert check_invariants(db) == [] and check_revenue_invariants(db) == []


# --- 2 · Eventos fuera de orden -----------------------------------------------------------------------------------


@pytest.mark.parametrize("order", list(itertools.permutations(["capture", "provider_refund", "capture_again"])))
def test_events_in_any_order_leave_the_same_verified_revenue_and_nothing_invented(order):
    """Un cobro, un reembolso que hizo el proveedor por su cuenta y una reentrega del cobro, en los seis órdenes en que
    pueden llegar. El ingreso verificado es **siempre** 50.00. El reembolso solo se registra si llegó cuando ya existía
    el cobro que revierte; si llegó antes, queda como evidencia y **no** como una entrada inventada."""
    engine = make_engine()
    factory = session_factory(engine)
    provider = ScriptedPaymentProvider()
    watch = LedgerWatch()
    try:
        with factory() as db:
            payment = start_attempt(db, add_order(db, add_product(db), price="25.00", quantity=2), provider)
            payment_id = payment.id
        # `capture` y `capture_again` son el MISMO evento: el primero de los dos que llega es la entrega real.
        first_capture = min(order.index("capture"), order.index("capture_again"))
        refund_before_capture = order.index("provider_refund") < first_capture

        with factory() as db:
            payment = db.get(Payment, payment_id)
            capture_bytes = _signed(provider, SUCCEEDED, payment, event_id="evt_capture")
            refund_bytes = _signed(
                provider,
                REFUND_SUCCEEDED,
                payment,
                amount="10.00",
                provider_refund_ref="re_by_provider",
                event_id="evt_provider_refund",
            )
        bytes_of = {"capture": capture_bytes, "capture_again": capture_bytes, "provider_refund": refund_bytes}

        for step in order:
            with factory() as db:
                headers, raw = bytes_of[step]
                ingress(db, provider).receive(provider.name, headers, raw)
            with factory() as db:
                broken = check_invariants(db) + check_revenue_invariants(db) + watch.check(db)
                assert broken == [], f"order {order}, after {step}: {broken}"

        with factory() as db:
            entries = _entries(db)
            captures = [e for e in entries if e.kind == "CAPTURE"]
            refunds = [e for e in entries if e.kind == "REFUND"]
            assert [Decimal(str(e.amount)) for e in captures] == [Decimal("50")], "one capture, whatever the order"
            if refund_before_capture:
                assert refunds == [], "a refund that arrived before its capture is evidence, not an entry"
                refund_event = db.scalars(
                    select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_provider_refund")
                ).one()
                assert refund_event.processing_status != "APPLIED" and refund_event.processing_status != "RECEIVED"
                assert Decimal(str(refund_event.amount)) == Decimal("10")
            else:
                assert [Decimal(str(e.amount)) for e in refunds] == [Decimal("10")]
    finally:
        engine.dispose()


# --- 3 · La tormenta concurrente, con el oráculo del registro ---------------------------------------------------


def test_a_concurrent_storm_leaves_the_ledger_matching_the_payments_and_nothing_rewritten():
    for base_seed in (31, 32, 33):
        with ephemeral_postgres() as engine:
            first, _ = make_world(base_seed * 100, engine)
            worlds = [first]
            for offset in range(1, 5):
                worlds.append(
                    World(
                        factory=first.factory,
                        rnd=random.Random(base_seed * 100 + offset),
                        pay=first.pay,
                        ful=first.ful,
                        product=first.product,
                        quote=first.quote,
                    )
                )
            for world in worlds:
                world.sweep_after = datetime.timedelta(seconds=30)
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

            assert not [leak for w in worlds for leak in w.leaks], f"seed {base_seed}"
            watch = LedgerWatch()
            with Session(engine) as db:
                broken = check_revenue_invariants(db) + watch.check(db)
            assert broken == [], f"seed {base_seed} after the storm: {broken}"

            worlds[0].sweep_after = datetime.timedelta(seconds=-1)
            run_operation(worlds[0], "reconcile_events", reconcile_events)
            run_operation(worlds[0], "sweep", sweep)
            for _ in range(80):
                with Session(engine) as db:
                    if not db.scalar(
                        select(ExternalAction.id).where(ExternalAction.status == "UNKNOWN_OUTCOME").limit(1)
                    ):
                        break
                run_operation(worlds[0], "resolve_by_hand", resolve_by_hand)
            run_operation(worlds[0], "reconcile_events", reconcile_events)
            with Session(engine) as db:
                broken = check_invariants(db) + check_revenue_invariants(db) + watch.check(db)
                assert db.scalars(select(RevenueLedgerEntry)).all(), (
                    f"seed {base_seed}: the storm never reached the money"
                )
            assert broken == [], f"seed {base_seed} after recovery: {broken}"


# --- 4 · La reconciliación no reinterpreta lo desconocido ----------------------------------------------------------


@pytest.mark.parametrize("passes", [1, 3, 10])
def test_no_number_of_reconciliation_passes_changes_an_unknown_outcome_or_its_reserved_money(passes):
    engine = make_engine()
    factory = session_factory(engine)
    try:
        lost = ScriptedPaymentProvider("timeout_after")  # ejecutó, y la respuesta se perdió
        with factory() as db:
            payment = start_attempt(db, add_order(db, add_product(db), price="25.00", quantity=2), lost)
            payment_id = payment.id
            assert reload(db, payment).status == "UNKNOWN_OUTCOME"
            before = _unknown_state(db)

        for _ in range(passes):
            for age in (datetime.timedelta(seconds=-1), datetime.timedelta(days=-365)):
                with factory() as db:
                    ActionReconciler(db, older_than=age).sweep()
                with factory() as db:
                    EventReconciler(db, older_than=age, max_attempts=5).sweep()
        with factory() as db:
            assert _unknown_state(db) == before, "a reconciliation reinterpreted an unknown outcome"
            assert db.get(Payment, payment_id).status == "UNKNOWN_OUTCOME"
            assert _entries(db) == []
        assert len(lost.calls) == 1, "no pass repeated the call that may already have executed"
    finally:
        engine.dispose()


def test_a_process_that_dies_after_crossing_the_frontier_is_unknown_and_no_scheduled_sweep_releases_it():
    """La caída **después de `begin_call`**, con el barrido programado y el registro delante. Lo que pudo salir no puede
    darse por no enviado: el barrido lo marca desconocido, **no lo libera**, y mientras sea desconocido nada nuevo se
    envía (un segundo cobro podría ser un cobro doble)."""
    engine = make_engine()
    factory = session_factory(engine)
    died = ScriptedPaymentProvider("die")
    try:
        with factory() as db:
            order = add_order(db, add_product(db), price="25.00", quantity=2)
            order_id = order.id
            with pytest.raises(KeyboardInterrupt):
                start_attempt(db, order, died)
            db.rollback()

        with factory() as db:
            action = db.scalars(select(ExternalAction).order_by(ExternalAction.created_at)).one()
            assert action.status == "CALLING", "the process died holding an open call"
            action_id = action.id
            assert db.scalars(select(Payment)).one().status == "OPENING"

        for _ in range(3):
            with factory() as db:
                report = ActionReconciler(db, older_than=datetime.timedelta(seconds=-1)).sweep()
            with factory() as db:
                action = db.get(ExternalAction, action_id)
                assert action.status == "UNKNOWN_OUTCOME", "a call that may have executed is unknown, never released"
                assert report.released == [], "the sweep released something that may have been sent"
                assert db.scalars(select(Payment)).one().status == "UNKNOWN_OUTCOME"
                assert check_invariants(db) == [] and check_revenue_invariants(db) == []

        with factory() as db:
            with pytest.raises(Exception) as refused:  # noqa: PT011 - un conflicto del dominio
                start_attempt(db, db.get(Order, order_id), ScriptedPaymentProvider())
            assert "unknown" in str(refused.value).lower() or "still" in str(refused.value).lower()
            db.rollback()
        assert len(died.calls) == 1, "nothing was sent again behind the unknown outcome"
    finally:
        engine.dispose()


def _unknown_state(db: Session) -> dict:
    return {
        a.id: (a.status, a.attempts if hasattr(a, "attempts") else None, a.sequence)
        for a in db.scalars(select(ExternalAction).where(ExternalAction.status == "UNKNOWN_OUTCOME"))
    }


def test_an_idempotent_ingress_for_an_applied_event_does_not_touch_the_ledger_after_the_reconciler_ran():
    """El proveedor reentrega, tarde, un evento que el reconciliador ya aplicó: no suma, no resta, no reescribe."""
    engine = make_engine()
    factory = session_factory(engine)
    provider = ScriptedPaymentProvider()
    try:
        with factory() as db:
            payment = start_attempt(db, add_order(db, add_product(db), price="25.00", quantity=2), provider)
            stored, redelivery = _stored_but_not_applied(db, provider, payment)
            stored_id = stored.id
        with factory() as db:
            EventReconciler(db, older_than=datetime.timedelta(seconds=-1), max_attempts=5).sweep()
        with factory() as db:
            before = [(e.id, str(e.amount), e.recorded_at) for e in _entries(db)]
            assert len(before) == 1
            assert db.get(PaymentEvent, stored_id).processing_status == "APPLIED"
            db.execute(update(PaymentEvent).where(PaymentEvent.id == stored_id).values(note=PaymentEvent.note))
            db.commit()
        # La reentrega del proveedor: exactamente los mismos bytes firmados otra vez.
        with factory() as db:
            result = ingress(db, provider).receive(provider.name, *redelivery)
            assert result.duplicate is True
        with factory() as db:
            assert [(e.id, str(e.amount), e.recorded_at) for e in _entries(db)] == before
            assert check_revenue_invariants(db) == []
    finally:
        engine.dispose()


def test_the_simulation_settings_used_here_are_the_ones_the_rest_of_the_suite_uses():
    """Una guarda tonta: si `SIMULATION` dejara de ser una simulación, estas pruebas dejarían de probar lo que dicen."""
    assert SIMULATION.operating_in_simulation is True
    assert ingress is not None
