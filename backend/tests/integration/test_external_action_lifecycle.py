"""El ciclo de vida de una acción externa (hardening pre-M44, ADR 0024).

Las preguntas que una caída o un timeout dejan abiertas, una por una, con un proveedor **falso** que se
comporta como se le dice y cuenta los efectos que ha producido «en el mundo real»:

- ¿se puede liberar el presupuesto reservado? Solo si se sabe que la petición **no** salió o que el proveedor
  confirmó que no hubo efecto;
- ¿se puede volver a intentar? Solo con la misma clave (el proveedor no repite el efecto) o si se sabe que no
  hubo efecto; nunca a ciegas;
- ¿se puede dar por hecho? Solo si el proveedor lo confirmó (o una persona lo comprobó y lo dejó escrito).

Casos de la fase 1: A (cae antes de reservar), B (reservado, no llamó), C (cae a mitad de la llamada), D (el
proveedor ejecutó y la respuesta se perdió), E (no ejecutó y se agota el tiempo), F (rechazo confirmado).
"""

import datetime

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import (
    ActionStatus,
    SimulatedAdapter,
    derive_idempotency_key,
)
from app.actions.service import ExternalActionService, ExternalActionStateError
from app.budgets.service import BudgetLedgerService
from app.core.errors import (
    ExternalActionFailedError,
    ExternalOutcomeUnknownError,
    PipelineDisabledError,
    ValidationError,
)
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.external_action import ExternalAction
from app.gates.action_gate import GateOutcome, HumanApproval, SideEffectAction
from app.gates.service import ActionGateService
from app.pipeline.kill_switch import PipelineKillSwitchService

OWNER = "owner@amazona.local"
REFERENCE = "pipeline_step:run-1:marketing"
OPERATION = "activate_ads"
PAYLOAD = {"platform": "meta", "daily_budget": 100.0}


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def service(db: Session) -> ExternalActionService:
    BudgetLedgerService(db).authorise_budget(hard_limit=1_000.0, actor=OWNER)
    db.commit()
    return ExternalActionService(db)


def allocation(db: Session) -> tuple[float, float, float]:
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed), float(row.spent)


def prepare(service: ExternalActionService, db: Session, adapter, *, reference=REFERENCE, amount=100.0, payload=None):
    """Lo que hace el pipeline antes de llamar: abrir y reservar, todo confirmado."""
    action = service.open(
        reference=reference,
        adapter=adapter,
        operation=OPERATION,
        amount=amount,
        payload=payload if payload is not None else PAYLOAD,
        correlation_id="corr-1",
    )
    assert service.reserve(action)
    db.commit()
    return action


def run(service: ExternalActionService, action: ExternalAction, adapter) -> None:
    service.execute(action, adapter, PAYLOAD)


def events(db: Session, kind: str) -> int:
    return db.query(FinancialEvent).filter_by(type=kind).count()


# --- A: cae antes de que nada se confirme -------------------------------------------


def test_case_a_a_crash_before_the_commit_leaves_nothing_behind(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter()
    action = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )
    service.reserve(action)
    db.rollback()  # el proceso muere antes del commit

    assert db.query(ExternalAction).count() == 0
    assert allocation(db) == (0.0, 0.0, 0.0)
    assert adapter.effect_count == 0


# --- B: reservado y confirmado, la petición no salió --------------------------------


def test_case_b_a_reservation_whose_request_never_left_is_released_by_the_sweeper(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter()
    action = prepare(service, db, adapter)
    assert allocation(db) == (100.0, 0.0, 0.0)  # el proceso muere aquí: PENDING, sin llamar

    swept = service.reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    db.refresh(action)
    assert swept == {"released": [action.id], "unknown": []}
    assert action.status == ActionStatus.FAILED_CONFIRMED.value
    assert allocation(db) == (0.0, 0.0, 0.0)  # se sabe que no hubo efecto: se libera
    assert adapter.requests == []


def test_the_sweeper_leaves_a_fresh_operation_alone(db: Session, service: ExternalActionService):
    action = prepare(service, db, FakeProviderAdapter())

    swept = service.reconcile_interrupted(older_than=datetime.timedelta(hours=1))

    db.refresh(action)
    assert swept == {"released": [], "unknown": []}
    assert action.status == ActionStatus.PENDING.value
    assert allocation(db) == (100.0, 0.0, 0.0)


# --- C: cae a mitad de la llamada ---------------------------------------------------


def test_case_c_a_crash_mid_call_is_unknown_and_the_reservation_is_never_released(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter(behaviors=["die"])
    action = prepare(service, db, adapter)

    with pytest.raises(KeyboardInterrupt):
        run(service, action, adapter)
    db.rollback()

    db.refresh(action)
    assert action.status == ActionStatus.CALLING.value  # la frontera quedó confirmada antes de salir
    swept = service.reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))
    db.refresh(action)
    assert swept == {"released": [], "unknown": [action.id]}
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert allocation(db) == (100.0, 0.0, 0.0)  # puede haberse ejecutado: ni se libera ni se gasta
    assert events(db, "RELEASE") == 0


def test_the_next_attempt_after_a_crash_mid_call_finds_an_unknown_outcome(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter(behaviors=["die"])
    action = prepare(service, db, adapter)
    with pytest.raises(KeyboardInterrupt):
        run(service, action, adapter)
    db.rollback()

    interrupted = service.mark_interrupted(REFERENCE)

    assert interrupted is not None
    assert interrupted.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert service.mark_interrupted(REFERENCE) is not None  # y sigue siéndolo en la siguiente mirada


def test_marking_interrupted_ignores_an_operation_that_never_started(db: Session, service: ExternalActionService):
    prepare(service, db, FakeProviderAdapter())

    assert service.mark_interrupted(REFERENCE) is None
    assert service.mark_interrupted("pipeline_step:other:marketing") is None


# --- D: el proveedor ejecutó y la respuesta se perdió -------------------------------


def test_case_d_a_lost_response_is_unknown_not_a_failure_and_keeps_the_reservation(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])
    action = prepare(service, db, adapter)

    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)

    db.refresh(action)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert adapter.effect_count == 1  # en el mundo real sí ocurrió
    assert allocation(db) == (100.0, 0.0, 0.0)  # y el sistema no lo da por hecho ni lo libera


def test_case_d_a_provider_that_can_be_asked_confirms_what_happened(db: Session, service: ExternalActionService):
    adapter = FakeLookupProviderAdapter(behaviors=["timeout_after"])
    action = prepare(service, db, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)

    status = service.reconcile(action, adapter, PAYLOAD)

    assert status is ActionStatus.SUCCEEDED
    assert allocation(db) == (0.0, 100.0, 100.0)
    assert adapter.effect_count == 1  # consultar no repite el efecto


def test_case_d_an_idempotent_provider_is_reconciled_by_repeating_the_same_key(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])  # sin consulta, pero con idempotencia
    action = prepare(service, db, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)

    status = service.reconcile(action, adapter, PAYLOAD)

    assert status is ActionStatus.SUCCEEDED
    assert adapter.effect_count == 1  # misma clave: el proveedor no repite el efecto
    assert {request.idempotency_key for request in adapter.requests} == {action.idempotency_key}
    assert allocation(db) == (0.0, 100.0, 100.0)


def test_a_provider_without_idempotency_or_lookup_is_never_replayed_blindly(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"])
    action = prepare(service, db, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)
    calls = len(adapter.requests)

    status = service.reconcile(action, adapter, PAYLOAD)

    assert status is ActionStatus.UNKNOWN_OUTCOME
    assert len(adapter.requests) == calls  # ni una petición más
    assert adapter.effect_count == 1
    assert allocation(db) == (100.0, 0.0, 0.0)  # hace falta una persona


def test_a_replay_that_is_rejected_or_times_out_proves_nothing(db: Session, service: ExternalActionService):
    for behavior in ("reject", "unreachable", "timeout_before"):
        adapter = FakeProviderAdapter(behaviors=["timeout_after", behavior])
        action = prepare(service, db, adapter, reference=f"ref-{behavior}")
        with pytest.raises(ExternalOutcomeUnknownError):
            run(service, action, adapter)

        assert service.reconcile(action, adapter, PAYLOAD) is ActionStatus.UNKNOWN_OUTCOME
        db.refresh(action)
        assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert events(db, "RELEASE") == 0  # ninguna reserva se liberó a ciegas


# --- E: no ejecutó y se agota el tiempo ---------------------------------------------


def test_case_e_a_timeout_before_execution_still_looks_unknown_from_the_outside(
    db: Session, service: ExternalActionService
):
    adapter = FakeLookupProviderAdapter(behaviors=["timeout_before"])
    action = prepare(service, db, adapter)

    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)
    assert allocation(db) == (100.0, 0.0, 0.0)  # desde fuera no se distingue de D: no se libera

    status = service.reconcile(action, adapter, PAYLOAD)  # solo la consulta lo aclara

    assert status is ActionStatus.FAILED_CONFIRMED
    assert allocation(db) == (0.0, 0.0, 0.0)
    assert adapter.effect_count == 0


# --- F: rechazo confirmado ----------------------------------------------------------


@pytest.mark.parametrize("behavior", ["reject", "unreachable"])
def test_case_f_a_confirmed_failure_releases_the_reservation(
    db: Session, service: ExternalActionService, behavior: str
):
    adapter = FakeProviderAdapter(behaviors=[behavior])
    action = prepare(service, db, adapter)

    with pytest.raises(ExternalActionFailedError):
        run(service, action, adapter)

    db.refresh(action)
    assert action.status == ActionStatus.FAILED_CONFIRMED.value
    assert allocation(db) == (0.0, 0.0, 0.0)
    assert adapter.effect_count == 0


# --- La respuesta de la llamada original llega tarde -------------------------------------


def seen_in_flight_by_another_executor(db: Session, service: ExternalActionService, adapter) -> ExternalAction:
    """La llamada sigue en vuelo; otro ejecutor la ve `CALLING`, no sabe si su dueño sigue vivo y la marca."""
    action = prepare(service, db, adapter)
    service.begin_call(action)
    assert service.mark_interrupted(REFERENCE) is not None
    db.refresh(action)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    return action


def test_the_late_success_of_the_original_call_closes_an_unknown_outcome_and_commits(
    db: Session, service: ExternalActionService
):
    action = seen_in_flight_by_another_executor(db, service, FakeProviderAdapter())

    service.finish(action, ActionStatus.SUCCEEDED)  # el dueño de la llamada, vivo, recibe por fin su respuesta

    db.refresh(action)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert allocation(db) == (0.0, 100.0, 100.0)
    closing = db.query(AuditLog).filter_by(action="external_action.succeeded").one()
    assert closing.before == {"status": "UNKNOWN_OUTCOME"}
    assert closing.after["late_response"] is True


def test_the_late_rejection_of_the_original_call_closes_an_unknown_outcome_and_releases(
    db: Session, service: ExternalActionService
):
    action = seen_in_flight_by_another_executor(db, service, FakeProviderAdapter())

    service.finish(action, ActionStatus.FAILED_CONFIRMED, error="the provider refused")

    db.refresh(action)
    assert action.status == ActionStatus.FAILED_CONFIRMED.value
    assert allocation(db) == (0.0, 0.0, 0.0)


def test_a_late_timeout_of_the_original_call_leaves_an_unknown_outcome_as_it_was(
    db: Session, service: ExternalActionService
):
    action = seen_in_flight_by_another_executor(db, service, FakeProviderAdapter())

    service.finish(action, ActionStatus.UNKNOWN_OUTCOME, error="timed out too")  # no es un error: ya estaba así

    db.refresh(action)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert allocation(db) == (100.0, 0.0, 0.0)


def test_nothing_but_a_response_a_lookup_or_a_person_closes_an_unknown_outcome(
    db: Session, service: ExternalActionService
):
    """Ni el barrido, ni volver a mirar, ni volver a abrirla, ni intentar ejecutarla otra vez."""
    action = seen_in_flight_by_another_executor(db, service, FakeProviderAdapter())

    service.reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))
    service.mark_interrupted(REFERENCE)
    reopened = service.open(
        reference=REFERENCE,
        adapter=FakeProviderAdapter(),
        operation=OPERATION,
        amount=100.0,
        payload=PAYLOAD,
        correlation_id="c",
    )
    with pytest.raises(ExternalActionStateError):
        service.begin_call(action)

    db.refresh(action)
    assert reopened.id == action.id
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value
    assert allocation(db) == (100.0, 0.0, 0.0)


# --- Éxito --------------------------------------------------------------------------


def test_a_confirmed_success_commits_the_reservation_and_is_never_executed_twice(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter()
    action = prepare(service, db, adapter)

    run(service, action, adapter)
    run(service, action, adapter)  # un reintento tras un éxito ya confirmado

    db.refresh(action)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert adapter.effect_count == 1
    assert len(adapter.requests) == 1
    assert allocation(db) == (0.0, 100.0, 100.0)


def test_begin_call_cannot_run_twice_for_the_same_operation(db: Session, service: ExternalActionService):
    action = prepare(service, db, FakeProviderAdapter())

    service.begin_call(action)

    with pytest.raises(ExternalActionStateError):
        service.begin_call(action)


def test_the_kill_switch_is_checked_again_right_before_the_call(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter()
    action = prepare(service, db, adapter)
    PipelineKillSwitchService(db).disable(reason="incident", actor="ops@amazona.local", correlation_id="c")

    with pytest.raises(PipelineDisabledError):
        run(service, action, adapter)

    db.refresh(action)
    assert action.status == ActionStatus.PENDING.value  # no salió nada
    assert adapter.requests == []
    assert allocation(db) == (100.0, 0.0, 0.0)  # sigue reservado: se reanuda o lo libera el barrido


# --- Resolver a mano ----------------------------------------------------------------


def unknown_action(db: Session, service: ExternalActionService) -> ExternalAction:
    adapter = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"])
    action = prepare(service, db, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)
    return action


def test_a_person_confirming_the_effect_commits_the_reservation_and_leaves_a_trail(
    db: Session, service: ExternalActionService
):
    action = unknown_action(db, service)

    service.resolve(action, succeeded=True, actor="owner@amazona.local", reason="seen in the ads console")

    db.refresh(action)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert action.resolved_by == "owner@amazona.local"
    assert allocation(db) == (0.0, 100.0, 100.0)
    trail = db.query(AuditLog).filter_by(action="external_action.resolve").one()
    assert trail.actor == "owner@amazona.local"
    assert trail.before == {"status": "UNKNOWN_OUTCOME"}
    assert trail.after["why"] == "seen in the ads console"


def test_a_person_confirming_there_was_no_effect_releases_the_reservation(db: Session, service: ExternalActionService):
    action = unknown_action(db, service)

    service.resolve(action, succeeded=False, actor="owner@amazona.local", reason="no campaign exists")

    db.refresh(action)
    assert action.status == ActionStatus.FAILED_CONFIRMED.value
    assert allocation(db) == (0.0, 0.0, 0.0)


def test_resolving_needs_a_reason(db: Session, service: ExternalActionService):
    action = unknown_action(db, service)

    with pytest.raises(ValidationError):
        service.resolve(action, succeeded=True, actor="owner@amazona.local", reason="   ")

    db.refresh(action)
    assert action.status == ActionStatus.UNKNOWN_OUTCOME.value


def test_an_operation_can_only_be_resolved_once_and_the_ledger_moves_once(db: Session, service: ExternalActionService):
    action = unknown_action(db, service)
    service.resolve(action, succeeded=True, actor="owner@amazona.local", reason="seen")

    with pytest.raises(ExternalActionStateError):
        service.resolve(action, succeeded=False, actor="other@amazona.local", reason="changed my mind")

    assert allocation(db) == (0.0, 100.0, 100.0)
    assert events(db, "COMMIT") == 1
    assert events(db, "RELEASE") == 0


def test_a_release_never_takes_from_the_reservation_of_another_operation(db: Session, service: ExternalActionService):
    """Sin reserva viva propia no hay nada que liberar, aunque haya otra de otro paso."""
    other = prepare(service, db, FakeProviderAdapter(), reference="pipeline_step:run-2:marketing", amount=300.0)
    adapter = FakeProviderAdapter(behaviors=["reject"])
    action = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )
    db.commit()  # abierta, pero nunca reservada

    with pytest.raises(ExternalActionFailedError):
        run(service, action, adapter)

    assert allocation(db) == (300.0, 0.0, 0.0)  # la reserva de la otra operación sigue intacta
    db.refresh(other)
    assert other.status == ActionStatus.PENDING.value


def test_without_a_budget_a_failure_moves_no_ledger(db: Session):
    service = ExternalActionService(db)
    adapter = FakeProviderAdapter(behaviors=["reject"])
    action = prepare(service, db, adapter)

    with pytest.raises(ExternalActionFailedError):
        run(service, action, adapter)

    assert db.query(FinancialEvent).count() == 0


# --- Abrir: una operación por sitio, y qué se reutiliza -----------------------------


def test_reopening_an_unfinished_operation_returns_the_same_one_with_the_same_key(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter()
    first = prepare(service, db, adapter)

    second = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )

    assert second.id == first.id
    assert second.idempotency_key == first.idempotency_key
    assert db.query(ExternalAction).count() == 1


def test_a_different_request_cannot_take_over_an_unfinished_operation(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter()
    prepare(service, db, adapter)

    with pytest.raises(ValidationError):
        service.open(
            reference=REFERENCE,
            adapter=adapter,
            operation=OPERATION,
            amount=250.0,
            payload=PAYLOAD,
            correlation_id="c",
        )


def test_a_confirmed_failure_lets_a_new_operation_open_with_a_new_key(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter(behaviors=["reject"])
    first = prepare(service, db, adapter)
    with pytest.raises(ExternalActionFailedError):
        run(service, first, adapter)

    second = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )

    assert second.id != first.id
    assert second.sequence == 2
    assert second.idempotency_key != first.idempotency_key  # una operación nueva, no un reintento


def test_an_effect_that_happened_but_was_not_recorded_is_reused_not_repeated(
    db: Session, service: ExternalActionService
):
    adapter = FakeProviderAdapter()
    first = prepare(service, db, adapter)
    run(service, first, adapter)  # SUCCEEDED, y el proceso cae antes de registrarlo localmente

    again = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )
    run(service, again, adapter)

    assert again.id == first.id
    assert adapter.effect_count == 1


def test_once_applied_a_new_operation_can_open(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter()
    first = prepare(service, db, adapter)
    run(service, first, adapter)
    service.mark_applied(first)
    db.commit()

    second = service.open(
        reference=REFERENCE, adapter=adapter, operation=OPERATION, amount=100.0, payload=PAYLOAD, correlation_id="c"
    )

    assert second.id != first.id


def test_an_unknown_outcome_keeps_the_site_and_blocks_opening_another(db: Session, service: ExternalActionService):
    action = unknown_action(db, service)

    again = service.open(
        reference=REFERENCE,
        adapter=FakeProviderAdapter(supports_idempotency=False),
        operation=OPERATION,
        amount=100.0,
        payload=PAYLOAD,
        correlation_id="c",
    )

    assert again.id == action.id  # sigue siendo la misma operación, sin resolver


# --- La clave hacia el proveedor ----------------------------------------------------


def test_the_provider_key_is_stable_per_operation_and_distinct_otherwise():
    assert derive_idempotency_key("ref-a", 1) == derive_idempotency_key("ref-a", 1)
    assert derive_idempotency_key("ref-a", 1) != derive_idempotency_key("ref-a", 2)
    assert derive_idempotency_key("ref-a", 1) != derive_idempotency_key("ref-b", 1)
    assert len(derive_idempotency_key("ref-a", 1)) <= 80


def test_the_key_is_only_sent_to_a_provider_that_declares_idempotency(db: Session, service: ExternalActionService):
    with_support = FakeProviderAdapter()
    without_support = FakeProviderAdapter(supports_idempotency=False)

    run(service, prepare(service, db, with_support, reference="ref-1"), with_support)
    run(service, prepare(service, db, without_support, reference="ref-2"), without_support)

    assert with_support.requests[0].idempotency_key is not None
    assert without_support.requests[0].idempotency_key is None


def test_a_retry_after_the_same_site_sends_the_same_key(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])
    action = prepare(service, db, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        run(service, action, adapter)

    service.reconcile(action, adapter, PAYLOAD)

    assert len({request.idempotency_key for request in adapter.requests}) == 1


def test_the_simulated_adapter_is_idempotent_and_has_no_real_effect():
    adapter = SimulatedAdapter()

    assert adapter.supports_idempotency is True
    assert adapter.name == "simulated"


# --- Auditoría ----------------------------------------------------------------------


def test_every_step_of_the_lifecycle_leaves_an_audit_row(db: Session, service: ExternalActionService):
    adapter = FakeProviderAdapter()
    action = prepare(service, db, adapter)
    run(service, action, adapter)

    recorded = [row.action for row in db.query(AuditLog).filter(AuditLog.action.like("external_action.%"))]

    assert sorted(recorded) == ["external_action.call_started", "external_action.open", "external_action.succeeded"]


# --- El veto del ActionGate ---------------------------------------------------------


def test_an_unresolved_outcome_vetoes_the_action_even_with_a_human_approval(db: Session):
    gate = ActionGateService(db)

    decision = gate.evaluate(
        SideEffectAction.PUBLISH_PRODUCT,
        human_approval=HumanApproval.GRANTED,
        actor_role="owner",
        unresolved_outcome=True,
    )

    assert decision.outcome is GateOutcome.DENY
    assert any("unknown outcome" in reason for reason in decision.reasons)


def test_without_an_unresolved_outcome_the_same_approval_allows_it(db: Session):
    decision = ActionGateService(db).evaluate(
        SideEffectAction.PUBLISH_PRODUCT, human_approval=HumanApproval.GRANTED, actor_role="owner"
    )

    assert decision.outcome is GateOutcome.ALLOW
