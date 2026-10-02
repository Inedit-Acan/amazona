"""Los observadores de transición de una acción externa (Milestone 44, ADR 0028 §3).

Lo que se prueba, sin ningún dominio real y con un proveedor **falso**:

- cada camino que mueve una acción avisa al observador de su referencia, con el estado anterior, el nuevo y la
  respuesta cuando la hay;
- el aviso ocurre **dentro de la transacción de la transición**: si el observador falla, la transición no se
  confirma (la acción no queda movida con su dominio sin mover);
- un observador solo atiende las referencias de su prefijo, y sin observadores todo se comporta como antes.
"""

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import ActionStatus
from app.actions.observers import observers_for
from app.actions.service import ExternalActionService
from app.core.errors import ExternalOutcomeUnknownError
from app.db.base import Base
from app.db.models.external_action import ExternalAction

SITE = "order_probe:one"
OPERATION = "probe.do"


class Recorder:
    """Un observador que anota lo que se le avisa y deja una fila de rastro en la transacción."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str | None]] = []

    def on_transition(self, db, action, *, previous, current, response):
        self.calls.append((action.reference, previous, current, response.reference if response else None))


class Failing:
    def on_transition(self, db, action, *, previous, current, response):
        raise RuntimeError("the domain projection failed")


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


def service_with(db: Session, *observers: tuple[str, object]) -> ExternalActionService:
    return ExternalActionService(db, observers=list(observers))  # type: ignore[arg-type]


def open_action(service: ExternalActionService, adapter, reference: str = SITE) -> ExternalAction:
    action = service.open(
        reference=reference,
        adapter=adapter,
        operation=OPERATION,
        amount=None,
        payload={"k": 1},
        correlation_id="c-1",
    )
    service._db.commit()
    return action


def test_a_successful_call_notifies_the_start_and_the_close_with_the_response(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)

    service.execute(action, adapter, {"k": 1})

    assert [(prev, cur) for _, prev, cur, _ in recorder.calls] == [("PENDING", "CALLING"), ("CALLING", "SUCCEEDED")]
    assert recorder.calls[1][3] is not None, "the provider's response travels with the closing transition"


def test_a_confirmed_failure_notifies_failed_confirmed(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter(behaviors=["reject"])
    action = open_action(service, adapter)

    with pytest.raises(Exception):  # noqa: B017,PT011 - ExternalActionFailedError
        service.execute(action, adapter, {"k": 1})

    assert [(p, c) for _, p, c, _ in recorder.calls] == [("PENDING", "CALLING"), ("CALLING", "FAILED_CONFIRMED")]


def test_a_timeout_notifies_an_unknown_outcome(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])
    action = open_action(service, adapter)

    with pytest.raises(ExternalOutcomeUnknownError):
        service.execute(action, adapter, {"k": 1})

    assert [(p, c) for _, p, c, _ in recorder.calls] == [("PENDING", "CALLING"), ("CALLING", "UNKNOWN_OUTCOME")]


def test_a_late_response_after_an_unknown_outcome_notifies_from_unknown(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])
    action = open_action(service, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        service.execute(action, adapter, {"k": 1})

    service.finish(action, ActionStatus.SUCCEEDED)  # la llamada original responde por fin

    assert recorder.calls[-1][1:3] == ("UNKNOWN_OUTCOME", "SUCCEEDED")


def test_the_sweep_notifies_both_sides_of_the_durability_frontier(db):
    import datetime

    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter()
    never_sent = open_action(service, adapter, "order_probe:never-sent")
    in_flight = open_action(service, adapter, "order_probe:in-flight")
    service.begin_call(in_flight)  # PENDING -> CALLING y el proceso muere aquí
    recorder.calls.clear()

    result = service.reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

    assert never_sent.id in result["released"] and in_flight.id in result["unknown"]
    assert ("order_probe:never-sent", "PENDING", "FAILED_CONFIRMED", None) in recorder.calls
    assert ("order_probe:in-flight", "CALLING", "UNKNOWN_OUTCOME", None) in recorder.calls


def test_mark_interrupted_notifies_the_unknown_outcome(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)
    service.begin_call(action)
    recorder.calls.clear()

    assert service.mark_interrupted(SITE) is not None

    assert [(p, c) for _, p, c, _ in recorder.calls] == [("CALLING", "UNKNOWN_OUTCOME")]


def test_a_lookup_that_finds_the_operation_notifies_with_its_response(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeLookupProviderAdapter(behaviors=["timeout_after"])
    action = open_action(service, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        service.execute(action, adapter, {"k": 1})
    recorder.calls.clear()

    assert service.reconcile(action, adapter, {"k": 1}) is ActionStatus.SUCCEEDED

    assert recorder.calls[-1][1:3] == ("UNKNOWN_OUTCOME", "SUCCEEDED")
    assert recorder.calls[-1][3] is not None, "the response found by the lookup travels with the transition"


def test_a_human_resolution_notifies_the_closing_transition(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter(behaviors=["timeout_after"])
    action = open_action(service, adapter)
    with pytest.raises(ExternalOutcomeUnknownError):
        service.execute(action, adapter, {"k": 1})
    recorder.calls.clear()

    service.resolve(action, succeeded=False, actor="owner@amazona.local", reason="checked with the provider")

    assert [(p, c) for _, p, c, _ in recorder.calls] == [("UNKNOWN_OUTCOME", "FAILED_CONFIRMED")]


def test_a_failing_observer_stops_the_start_of_the_call_and_nothing_is_sent(db):
    service = service_with(db, ("order_probe:", Failing()))
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)

    with pytest.raises(RuntimeError, match="projection failed"):
        service.begin_call(action)
    db.rollback()
    db.refresh(action)

    assert action.status == ActionStatus.PENDING.value, "the transition was not committed"
    assert adapter.effects == [], "the request never left"


def test_a_failing_observer_does_not_commit_the_closing_transition(db):
    recorder = Recorder()
    service = service_with(db, ("order_probe:", recorder))
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)
    service.begin_call(action)
    broken = service_with(db, ("order_probe:", Failing()))

    with pytest.raises(RuntimeError, match="projection failed"):
        broken.finish(action, ActionStatus.SUCCEEDED)
    db.rollback()
    db.refresh(action)

    assert action.status == ActionStatus.CALLING.value, "an action never moves without its domain"


def test_an_observer_only_hears_about_its_own_prefix(db):
    mine, other = Recorder(), Recorder()
    service = service_with(db, ("order_probe:", mine), ("something_else:", other))
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)

    service.execute(action, adapter, {"k": 1})

    assert mine.calls and other.calls == []


def test_without_observers_the_action_behaves_exactly_as_before(db):
    service = ExternalActionService(db)  # el registro del producto, vacío en este milestone
    adapter = FakeProviderAdapter()
    action = open_action(service, adapter)

    service.execute(action, adapter, {"k": 1})

    db.refresh(action)
    assert action.status == ActionStatus.SUCCEEDED.value
    assert observers_for("pipeline_step:abc:marketing") == []
