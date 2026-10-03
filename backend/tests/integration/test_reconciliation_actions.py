# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""El barrido programado de acciones externas abandonadas (Milestone 45, ADR 0029 §1, §3 y §5), sobre SQLite y
PostgreSQL.

Lo que se afirma, una garantía por prueba:

- una `PENDING` vieja (nunca salió) se libera con su reserva; una `CALLING` vieja pasa a `UNKNOWN_OUTCOME` y
**conserva** su reserva: superar el umbral
  **nunca** es un `FAILED_CONFIRMED`;
- un `UNKNOWN_OUTCOME` no lo toca ningún barrido, nunca: ni lo cierra, ni lo repite, ni libera su reserva;
- `CALLING` se mide desde que **empezó la llamada**;
- un elemento que falla no aborta el lote; el barrido no tiene adaptador y no puede ejecutar nada;
- una respuesta tardía cierra lo que el barrido marcó desconocido; el compare-and-set decide entre quien llega primero;
- con varios reconciliadores a la vez (PostgreSQL real) cada acción se mueve **una** vez.
"""

import datetime

import pytest
from action_test_support import FakeProviderAdapter
from order_test_support import add_product
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    payments_of,
    run_together,
)
from reconciliation_test_support import (  # noqa: F401 - fixtures de pytest
    age_action,
    ago,
    authorise_budget,
    db,
    engine,
    factory,
    make_action,
    outstanding,
    status_of,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus
from app.actions.service import ExternalActionService
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.jobs.schemas import JobCancelledError
from app.orders.errors import OutcomeUnknownBlockError
from app.orders.payment_attempts import PaymentAttemptService
from app.reconciliation.actions import ActionReconciler

EVERYTHING = datetime.timedelta(seconds=-1)  # todo lo que no esté en marcha ahora mismo es «viejo»
FIFTEEN = datetime.timedelta(minutes=15)


@pytest.fixture()
def funded(db: Session) -> Session:
    authorise_budget(db)
    return db


def sweep(db: Session, older_than: datetime.timedelta = FIFTEEN, **kwargs):
    return ActionReconciler(db, older_than=older_than, **kwargs).sweep()


# --- Qué se libera, qué pasa a desconocido ----------------------------------------------------------------------------


def test_an_old_pending_action_never_sent_is_released_with_its_reservation(funded: Session):
    action = make_action(funded, state="PENDING", amount=40.0)
    assert outstanding(funded, action) == 40
    age_action(funded, action, updated=ago(minutes=30), created=ago(minutes=30))

    report = sweep(funded)

    assert report.released == [action.id] and report.marked_unknown == [] and report.failed == []
    assert status_of(funded, action) == "FAILED_CONFIRMED", "nothing was ever sent: this is a confirmed non-effect"
    assert outstanding(funded, action) == 0, "the reservation of what never left is released"


def test_a_recent_pending_action_is_left_alone(funded: Session):
    action = make_action(funded, state="PENDING")
    age_action(funded, action, updated=ago(minutes=5))

    report = sweep(funded)

    assert report.examined == 0 and status_of(funded, action) == "PENDING" and outstanding(funded, action) == 40


def test_an_old_calling_action_becomes_unknown_and_keeps_its_reservation(funded: Session):
    action = make_action(funded, state="CALLING", amount=40.0)
    age_action(funded, action, call_started=ago(minutes=30), updated=ago(minutes=30))

    report = sweep(funded)

    assert report.marked_unknown == [action.id] and report.released == []
    assert status_of(funded, action) == "UNKNOWN_OUTCOME", "exceeding the threshold is NEVER a confirmed failure"
    assert status_of(funded, action) != "FAILED_CONFIRMED"
    assert outstanding(funded, action) == 40, "it may have been executed: the money stays reserved"


def test_calling_is_measured_from_when_the_call_started_not_from_the_last_write(funded: Session):
    started_long_ago = make_action(funded, state="CALLING", reference="pipeline_step:run-1:a")
    started_just_now = make_action(funded, state="CALLING", reference="pipeline_step:run-1:b")
    age_action(funded, started_long_ago, call_started=ago(minutes=40), updated=ago(seconds=1))
    age_action(funded, started_just_now, call_started=ago(seconds=1), updated=ago(minutes=40))

    report = sweep(funded)

    assert report.marked_unknown == [started_long_ago.id]
    assert status_of(funded, started_long_ago) == "UNKNOWN_OUTCOME" and status_of(funded, started_just_now) == "CALLING"


# --- Un desconocido no lo toca ningún barrido
# --------------------------------------------------------------------------


def test_an_unknown_outcome_is_never_closed_repeated_or_released_by_any_number_of_sweeps(funded: Session):
    adapter = FakeProviderAdapter()
    action = make_action(funded, state="UNKNOWN_OUTCOME", amount=40.0, adapter=adapter)
    age_action(funded, action, updated=ago(days=30), call_started=ago(days=30), created=ago(days=30))
    effects_before = adapter.effect_count

    for _ in range(5):
        report = sweep(funded, EVERYTHING)
        assert report.examined == 0, "an unknown outcome is not a candidate: it waits for information or a person"

    assert status_of(funded, action) == "UNKNOWN_OUTCOME", "time does not close it"
    assert outstanding(funded, action) == 40, "and it does not release a cent"
    assert adapter.effect_count == effects_before and adapter.requests == [], (
        "the sweep has no adapter: it cannot call out"
    )


def test_the_sweep_has_no_adapter_and_never_calls_execute_or_reconcile(funded: Session, monkeypatch):
    make_action(funded, state="PENDING", reference="pipeline_step:run-1:a")
    make_action(funded, state="CALLING", reference="pipeline_step:run-1:b")

    def forbidden(*args, **kwargs):
        raise AssertionError("the scheduled sweep must never execute or reconcile an external action")

    monkeypatch.setattr(ExternalActionService, "execute", forbidden)
    monkeypatch.setattr(ExternalActionService, "reconcile", forbidden)

    report = sweep(funded, EVERYTHING)

    assert len(report.released) == 1 and len(report.marked_unknown) == 1 and report.failed == []


def test_a_late_response_closes_what_the_sweep_marked_unknown(funded: Session):
    adapter = FakeProviderAdapter()
    action = make_action(funded, state="CALLING", amount=40.0, adapter=adapter)
    sweep(funded, EVERYTHING)
    assert status_of(funded, action) == "UNKNOWN_OUTCOME"

    ExternalActionService(funded).finish(
        funded.get(ExternalAction, action.id, populate_existing=True),
        ActionStatus.SUCCEEDED,
        response=ActionResponse(reference="remote-1"),
    )

    assert status_of(funded, action) == "SUCCEEDED", (
        "the original call answered after all: that answer is authoritative"
    )
    assert outstanding(funded, action) == 0, "the reservation is committed, not released by a guess"
    late = [a for a in funded.scalars(select(AuditLog)) if a.after and a.after.get("late_response")]
    assert late, "the late response is on the audit trail"


# --- Cada elemento en su transacción
# ------------------------------------------------------------------------------------


def test_one_failing_element_does_not_abort_the_batch_and_leaves_a_trace(funded: Session, monkeypatch):
    first = make_action(funded, state="PENDING", reference="pipeline_step:run-1:a")
    poisoned = make_action(funded, state="PENDING", reference="pipeline_step:run-1:b")
    third = make_action(funded, state="CALLING", reference="pipeline_step:run-1:c")
    real = ExternalActionService.sweep_one

    def sweep_one(self, action_id: str) -> str:
        if action_id == poisoned.id:
            raise RuntimeError("an observer blew up")
        return real(self, action_id)

    monkeypatch.setattr(ExternalActionService, "sweep_one", sweep_one)

    report = sweep(funded, EVERYTHING)

    assert report.failed == [(poisoned.id, "RuntimeError")]
    assert sorted(report.released + report.marked_unknown) == sorted([first.id, third.id])
    assert status_of(funded, first) == "FAILED_CONFIRMED" and status_of(funded, third) == "UNKNOWN_OUTCOME"
    assert status_of(funded, poisoned) == "PENDING", "the poisoned one is untouched: it will be seen again next tick"
    trace = funded.scalars(select(AuditLog).where(AuditLog.action == "reconciliation.action_sweep_failed")).one()
    assert trace.resource == f"external_action:{poisoned.id}" and trace.after == {
        "error": "RuntimeError: an observer blew up"
    }


def test_a_database_error_leaves_only_its_type_in_the_trace_never_its_statement(funded: Session, monkeypatch):
    from sqlalchemy.exc import OperationalError

    action = make_action(funded, state="PENDING")

    def explode(self, action_id: str) -> str:
        raise OperationalError(
            "SELECT secret_column FROM somewhere WHERE x = 'sensitive'", {"x": "sensitive"}, Exception("boom")
        )

    monkeypatch.setattr(ExternalActionService, "sweep_one", explode)

    report = sweep(funded, EVERYTHING)

    assert report.failed == [(action.id, "OperationalError")]
    trace = funded.scalars(select(AuditLog).where(AuditLog.action == "reconciliation.action_sweep_failed")).one()
    assert trace.after == {"error": "OperationalError"}, "no SQL and no parameters in the audit trail"


def test_an_action_moved_between_listing_and_sweeping_is_a_lost_race_not_an_error(funded: Session, monkeypatch):
    action = make_action(funded, state="CALLING")
    listed = ExternalActionService(funded).stale_candidates(ago(seconds=-5))
    assert listed == [(action.id, "CALLING")]
    ExternalActionService(funded).finish(
        funded.get(ExternalAction, action.id), ActionStatus.SUCCEEDED, response=ActionResponse(reference="r")
    )  # la llamada terminó justo después de que el barrido la viera
    monkeypatch.setattr(ExternalActionService, "stale_candidates", lambda self, limit, batch=None: listed)

    report = sweep(funded, EVERYTHING)

    assert report.lost_race == 1 and report.marked_unknown == [] and report.failed == []
    assert status_of(funded, action) == "SUCCEEDED", "the compare-and-set did not touch what someone else closed"


def test_the_sweep_beats_the_heart_beat_of_its_job_and_stops_if_the_job_was_taken_away(funded: Session):
    for index in range(3):
        make_action(funded, state="PENDING", reference=f"pipeline_step:run-1:{index}")
    beats: list[int] = []

    def heartbeat() -> None:
        beats.append(1)

    ActionReconciler(funded, older_than=EVERYTHING).sweep(heartbeat=heartbeat)
    assert len(beats) == 3, "a heartbeat before each element keeps the lease alive"

    for index in range(3):
        make_action(funded, state="PENDING", reference=f"pipeline_step:run-2:{index}")

    def taken_away() -> None:
        raise JobCancelledError("the job is no longer held by this worker")

    with pytest.raises(JobCancelledError):
        ActionReconciler(funded, older_than=EVERYTHING).sweep(heartbeat=taken_away)


def test_the_batch_is_bounded_and_the_rest_waits_for_the_next_tick(funded: Session):
    ids = [make_action(funded, state="PENDING", reference=f"pipeline_step:run-1:{n}", amount=None).id for n in range(5)]

    first = ActionReconciler(funded, older_than=EVERYTHING, batch=2).sweep()
    second = ActionReconciler(funded, older_than=EVERYTHING, batch=2).sweep()
    third = ActionReconciler(funded, older_than=EVERYTHING, batch=2).sweep()

    assert [first.examined, second.examined, third.examined] == [2, 2, 1]
    assert sorted(first.released + second.released + third.released) == sorted(ids)


# --- A través del dominio: lo mismo que ve un pedido
# ----------------------------------------------------------------------


def test_a_payment_stuck_while_calling_becomes_unknown_blocks_new_attempts_and_is_never_failed(db: Session):
    order = add_order(db, add_product(db))
    provider = ScriptedPaymentProvider("die")
    with pytest.raises(KeyboardInterrupt):
        PaymentAttemptService(db, settings=SIMULATION, provider=provider).start(order.id, requester=REQUESTER)
    db.rollback()
    assert payments_of(db, order)[0].status == "OPENING"

    report = ActionReconciler(db, older_than=EVERYTHING).sweep()

    assert len(report.marked_unknown) == 1
    payment = payments_of(db, order)[0]
    assert payment.status == "UNKNOWN_OUTCOME", "the observer moved the payment in the same transaction as the action"
    with pytest.raises(OutcomeUnknownBlockError):
        PaymentAttemptService(db, settings=SIMULATION, provider=ScriptedPaymentProvider()).start(
            order.id, requester=REQUESTER
        )
    for _ in range(3):
        assert ActionReconciler(db, older_than=EVERYTHING).sweep().examined == 0
    assert payments_of(db, order)[0].status == "UNKNOWN_OUTCOME"


# --- Varios reconciliadores a la vez: PostgreSQL real
# ------------------------------------------------------------------------


def test_several_reconcilers_at_once_move_every_action_exactly_once(engine, factory):
    if engine.dialect.name != "postgresql":
        pytest.skip("races only exist on a database with real transactions")
    with factory() as setup:
        authorise_budget(setup)
        pending = [make_action(setup, state="PENDING", reference=f"pipeline_step:run-1:p{n}").id for n in range(8)]
        calling = [make_action(setup, state="CALLING", reference=f"pipeline_step:run-1:c{n}").id for n in range(8)]

    def job(session: Session):
        return ActionReconciler(session, older_than=EVERYTHING).sweep()

    results = run_together(engine, [job] * 6)

    reports = [r for r in results if not isinstance(r, Exception)]
    assert len(reports) == 6, [r for r in results if isinstance(r, Exception)]
    released = sorted(i for r in reports for i in r.released)
    unknown = sorted(i for r in reports for i in r.marked_unknown)
    assert released == sorted(pending), "every never-sent action was released by exactly one reconciler"
    assert unknown == sorted(calling), "every abandoned call became unknown by exactly one reconciler"
    assert all(not r.failed for r in reports)
    with factory() as check:
        statuses = {a.id: a.status for a in check.scalars(select(ExternalAction))}
        assert {statuses[i] for i in pending} == {"FAILED_CONFIRMED"} and {statuses[i] for i in calling} == {
            "UNKNOWN_OUTCOME"
        }
        events = [
            a
            for a in check.scalars(select(AuditLog))
            if a.action in ("external_action.release_unstarted", "external_action.unknown_outcome")
        ]
        assert len(events) == 16, "one audit entry per transition: nothing was done twice"
