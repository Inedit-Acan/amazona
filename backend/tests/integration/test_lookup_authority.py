# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""Una consulta solo cierra un `UNKNOWN_OUTCOME` si el adaptador declara que es autoritativa (Milestone 45, ADR 0029
§7).

El `lookup` de los simuladores es la memoria **de un proceso**: en otro proceso (un worker) devolvería «no existe»
para algo que la API sí «hizo», y
`reconcile()` lo leería como «el proveedor no lo tiene» y liberaría la reserva. Por eso saber consultar no basta: hay
que **declararlo**, completo
(`lookup_is_authoritative` y `lookup_settle_seconds`), y la ausencia de la declaración es «no».

Lo que se afirma: la declaración es explícita y segura por defecto; los simuladores no la hacen; sin ella no se
cierra nada ni se pasa a repetir la
petición; con ella, un «existe» cierra y un «no existe» solo vale pasado el tiempo de asentamiento; y ningún camino
programado ejecuta ni reconcilia.
"""

import datetime
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from action_test_support import FakeLookupProviderAdapter, FakeProviderAdapter
from reconciliation_test_support import (  # noqa: F401 - fixtures de pytest
    authorise_budget,
    db,
    engine,
    factory,
    make_action,
    outstanding,
    status_of,
)
from sqlalchemy.orm import Session

from app.actions.contract import ActionResponse, ActionStatus, has_authoritative_lookup, lookup_settle_seconds
from app.actions.service import ExternalActionService
from app.db.models.external_action import ExternalAction
from app.orders.simulated_fulfilment import SimulatedFulfilmentAdapter
from app.payments.providers.simulated import SimulatedPaymentProvider

APP = Path(__file__).resolve().parents[2] / "app"
STARTED = datetime.datetime(2026, 10, 3, 12, 0, tzinfo=datetime.UTC)


class Declared(FakeLookupProviderAdapter):
    def __init__(self, *, authoritative: bool, settle: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lookup_is_authoritative = authoritative
        self.lookup_settle_seconds = settle
        self.lookups = 0

    def lookup(self, idempotency_key: str):
        self.lookups += 1
        return super().lookup(idempotency_key)


class Undeclared(FakeProviderAdapter):
    """Sabe consultar pero **no declara nada**: el caso de un adaptador que olvida la capacidad."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lookups = 0

    def lookup(self, idempotency_key: str):
        self.lookups += 1
        return self._by_key.get(idempotency_key)


@pytest.fixture()
def funded(db: Session) -> Session:
    authorise_budget(db)
    return db


def unknown_action(db: Session, adapter, *, executed: bool = False) -> ExternalAction:
    action = make_action(db, state="UNKNOWN_OUTCOME", amount=40.0, adapter=adapter)
    db.execute(ExternalAction.__table__.update().where(ExternalAction.id == action.id).values(call_started_at=STARTED))
    db.commit()
    db.expire_all()
    action = db.get(ExternalAction, action.id, populate_existing=True)
    assert action is not None
    if executed:  # el proveedor sí lo ejecutó: su memoria tiene la operación
        adapter._by_key[action.idempotency_key] = ActionResponse(reference="remote-1")
    return action


def at(seconds: int) -> datetime.datetime:
    return STARTED + datetime.timedelta(seconds=seconds)


# --- La declaración -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ({}, False),
        ({"lookup_is_authoritative": True}, False),  # sin tiempo de asentamiento: incompleta
        ({"lookup_is_authoritative": False, "lookup_settle_seconds": 0}, False),
        ({"lookup_is_authoritative": "yes", "lookup_settle_seconds": 0}, False),  # solo `True` exacto
        ({"lookup_is_authoritative": 1, "lookup_settle_seconds": 0}, False),
        ({"lookup_is_authoritative": True, "lookup_settle_seconds": -1}, False),
        ({"lookup_is_authoritative": True, "lookup_settle_seconds": True}, False),  # un booleano no es un tiempo
        ({"lookup_is_authoritative": True, "lookup_settle_seconds": "30"}, False),
        ({"lookup_is_authoritative": True, "lookup_settle_seconds": 0}, True),
        ({"lookup_is_authoritative": True, "lookup_settle_seconds": 90}, True),
    ],
)
def test_the_declaration_is_explicit_complete_and_safe_by_default(attributes, expected):
    assert has_authoritative_lookup(SimpleNamespace(**attributes)) is expected


def test_the_settle_time_is_read_only_when_it_is_a_valid_declaration():
    assert lookup_settle_seconds(SimpleNamespace(lookup_settle_seconds=45)) == 45
    assert lookup_settle_seconds(SimpleNamespace(lookup_settle_seconds=-3)) == 0
    assert lookup_settle_seconds(SimpleNamespace()) == 0


def test_the_simulated_adapters_declare_that_their_lookup_is_not_authoritative():
    assert SimulatedPaymentProvider.lookup_is_authoritative is False
    assert SimulatedFulfilmentAdapter.lookup_is_authoritative is False
    assert not has_authoritative_lookup(SimulatedPaymentProvider(operations={}))
    assert not has_authoritative_lookup(SimulatedFulfilmentAdapter(operations={}))


# --- reconcile() ----------------------------------------------------------------------------------------------------


def test_a_lookup_that_is_not_declared_authoritative_closes_nothing_even_if_it_says_the_operation_exists(
    funded: Session,
):
    adapter = Undeclared()
    action = unknown_action(funded, adapter, executed=True)

    status = ExternalActionService(funded, clock=lambda: at(3600)).reconcile(action, adapter, {})

    assert status is ActionStatus.UNKNOWN_OUTCOME and status_of(funded, action) == "UNKNOWN_OUTCOME"
    assert adapter.lookups == 0, "it does not even ask: an answer it could not trust is not information"
    assert outstanding(funded, action) == 40, "the reservation stays"


def test_a_lookup_declared_not_authoritative_never_falls_back_to_replaying_the_request(funded: Session):
    adapter = Declared(authoritative=False, supports_idempotency=True)
    action = unknown_action(funded, adapter)

    status = ExternalActionService(funded, clock=lambda: at(3600)).reconcile(action, adapter, {})

    assert status is ActionStatus.UNKNOWN_OUTCOME
    assert adapter.effect_count == 0 and adapter.requests == [], "no blind repeat: reconcile did not call execute"


def test_a_worker_with_the_simulator_memory_would_have_said_no_such_operation_and_must_not_release(funded: Session):
    """El caso que motivó la regla: otro proceso, la memoria del simulador vacía."""
    action = make_action(funded, state="UNKNOWN_OUTCOME", amount=40.0)
    worker_side = SimulatedPaymentProvider(operations={})
    assert worker_side.lookup(action.idempotency_key) is None, "this is what a worker would see"

    status = ExternalActionService(funded, clock=lambda: at(3600)).reconcile(action, worker_side, {})

    assert status is ActionStatus.UNKNOWN_OUTCOME and status_of(funded, action) == "UNKNOWN_OUTCOME"
    assert outstanding(funded, action) == 40, "a guess from another process's memory does not free a cent"


def test_an_authoritative_lookup_that_finds_the_operation_closes_it_as_succeeded(funded: Session):
    adapter = Declared(authoritative=True, settle=60)
    action = unknown_action(funded, adapter, executed=True)

    status = ExternalActionService(funded, clock=lambda: at(1)).reconcile(action, adapter, {})

    assert status is ActionStatus.SUCCEEDED, "a positive is a positive: it does not wait for the settle window"
    assert status_of(funded, action) == "SUCCEEDED" and outstanding(funded, action) == 0


def test_an_authoritative_none_before_the_settle_window_is_still_unknown(funded: Session):
    adapter = Declared(authoritative=True, settle=60)
    action = unknown_action(funded, adapter)

    status = ExternalActionService(funded, clock=lambda: at(30)).reconcile(action, adapter, {})

    assert status is ActionStatus.UNKNOWN_OUTCOME and adapter.lookups == 1
    assert status_of(funded, action) == "UNKNOWN_OUTCOME" and outstanding(funded, action) == 40
    assert adapter.effect_count == 0


def test_an_authoritative_none_after_the_settle_window_means_the_provider_has_no_such_operation(funded: Session):
    adapter = Declared(authoritative=True, settle=60)
    action = unknown_action(funded, adapter)

    status = ExternalActionService(funded, clock=lambda: at(61)).reconcile(action, adapter, {})

    assert status is ActionStatus.FAILED_CONFIRMED and status_of(funded, action) == "FAILED_CONFIRMED"
    assert outstanding(funded, action) == 0, "only now, with the provider's own word, is the reservation released"


def test_without_the_instant_the_call_started_a_none_is_never_enough(funded: Session):
    adapter = Declared(authoritative=True, settle=0)
    action = unknown_action(funded, adapter)
    funded.execute(ExternalAction.__table__.update().where(ExternalAction.id == action.id).values(call_started_at=None))
    funded.commit()
    funded.expire_all()
    action = funded.get(ExternalAction, action.id, populate_existing=True)
    assert action is not None

    status = ExternalActionService(funded, clock=lambda: at(10**6)).reconcile(action, adapter, {})

    assert status is ActionStatus.UNKNOWN_OUTCOME, "conservative: it cannot prove the window has passed"


def test_an_idempotent_adapter_without_any_lookup_can_still_be_replayed_by_a_person_with_the_same_key(funded: Session):
    """La repetición con la misma clave sigue existiendo como acción humana explícita; el programador no la usa
    jamás."""
    adapter = FakeProviderAdapter(supports_idempotency=True)
    action = make_action(funded, state="UNKNOWN_OUTCOME", amount=40.0, adapter=adapter)

    status = ExternalActionService(funded).reconcile(action, adapter, {"k": "pipeline_step:run-1:marketing"})

    assert status is ActionStatus.SUCCEEDED and adapter.effect_count == 1


# --- Guardas de arquitectura
# -----------------------------------------------------------------------------------------------


def sources(*relative: str) -> dict[str, str]:
    return {path: (APP / path).read_text(encoding="utf-8") for path in relative}


def test_the_reconcilers_have_no_adapter_and_never_call_execute_reconcile_or_begin_call():
    files = sources(
        "reconciliation/actions.py",
        "reconciliation/events.py",
        "reconciliation/report.py",
        "jobs/recurring.py",
    )
    for path, source in files.items():
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        code = re.sub(r"#.*", "", code)
        assert not re.search(r"\badapter\b", code), f"{path} handles an adapter: a scheduled path must not"
        assert not re.search(r"_service\.(execute|reconcile|begin_call|resolve)\(", code), path
        assert not re.search(r"ExternalActionService\([^)]*\)\.(execute|reconcile|begin_call|resolve)\(", code), path


def test_the_scheduled_reconciliation_touches_no_network_library():
    files = sources(
        "reconciliation/actions.py",
        "reconciliation/events.py",
        "reconciliation/report.py",
        "reconciliation/config_check.py",
        "jobs/recurring.py",
        "api/reconciliation.py",
    )
    for path, source in files.items():
        assert not re.search(
            r"^\s*(import|from)\s+(httpx|requests|urllib|socket|http\.client|aiohttp)\b", source, re.M
        ), path


def test_the_provisional_ceiling_value_is_referenced_only_where_it_is_declared_and_reported():
    """Ninguna lógica depende de un valor fijo de 120 s: solo se declara, se usa como valor provisional de simulación
    y se informa de que lo es."""
    referencing = sorted(
        str(path.relative_to(APP)).replace("\\", "/")
        for path in APP.rglob("*.py")
        if "PROVISIONAL_EXTERNAL_CALL_MAX_SECONDS" in path.read_text(encoding="utf-8")
    )

    assert referencing == ["core/config.py", "reconciliation/report.py"]
