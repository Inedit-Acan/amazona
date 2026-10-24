"""Fault injection de ENSAYO (M51A): el inyector en memoria y las puertas de entorno.

No es una capacidad productiva. Con `fault_injection_enabled = false` (el valor por defecto) nada
de esto actúa. Cuando está
activado solo existe donde ya es seguro hacer pruebas: `development` y todos los proveedores
simulados. Un armado es UNA tarea
concreta de UN objetivo en UN intento, de UN solo uso, vive solo en memoria y caduca."""

import datetime

import pytest

from app.core.config import Environment, ProviderKind, Settings
from app.core.errors import ConflictError, ValidationError
from app.fault_injection import (
    ALLOWED_TASKS,
    FAULT_TTL,
    FaultInjector,
    InjectedFault,
    get_fault_injector,
    set_fault_injector,
)
from app.tasks.schemas import Task

NOW = datetime.datetime(2026, 10, 24, 12, 0, tzinfo=datetime.UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime.datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += datetime.timedelta(**kwargs)


def armed(injector: FaultInjector, **over):
    args = {
        "objective_id": "obj-1",
        "task_name": "product_validation",
        "attempt": 1,
        "armed_by": "owner-1",
        "correlation_id": "corr-1",
    }
    args.update(over)
    return injector.arm(**args)


def task(**over) -> Task:
    base = {
        "project_id": "p1",
        "objective_id": "obj-1",
        "name": "product_validation",
        "capability": "market_validation",
        "retry_count": 0,
    }
    base.update(over)
    return Task(**base)


# --- Los ajustes: apagado por defecto y solo en development + simulación
# ---------------------------------------------------------


def dev(**over) -> Settings:
    return Settings(_env_file=None, **over)


def test_it_is_off_by_default_and_nothing_is_allowed():
    settings = dev()
    assert settings.fault_injection_enabled is False
    assert settings.fault_injection_allowed is False
    settings.validate_for_startup()  # y arrancar así no cambia nada


def test_B_development_with_every_provider_mock_allows_it():
    settings = dev(fault_injection_enabled=True)
    assert settings.environment is Environment.DEVELOPMENT
    settings.validate_for_startup()
    assert settings.fault_injection_allowed is True


@pytest.mark.parametrize("environment", [Environment.PRODUCTION, Environment.STAGING])
def test_C_D_enabled_in_production_or_staging_refuses_to_start(environment):
    settings = dev(
        environment=environment,
        fault_injection_enabled=True,
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        cors_origins=["https://app.example.com"],
    )
    with pytest.raises(RuntimeError, match="fault injection"):
        settings.validate_for_startup()
    assert settings.fault_injection_allowed is False


@pytest.mark.parametrize("environment", [Environment.TEST, Environment.DEMO])
def test_enabled_outside_development_refuses_to_start(environment):
    with pytest.raises(RuntimeError, match="fault injection"):
        dev(environment=environment, fault_injection_enabled=True).validate_for_startup()


@pytest.mark.parametrize("kind", [ProviderKind.SANDBOX, ProviderKind.REAL, ProviderKind.COMPOSITE])
@pytest.mark.parametrize("field", ["payments_provider", "suppliers_provider", "exchange_rate_provider", "ads_provider"])
def test_E_enabled_with_a_provider_that_is_not_a_mock_refuses_to_start(field, kind):
    settings = dev(fault_injection_enabled=True, **{field: kind})
    assert settings.operating_in_simulation is False
    with pytest.raises(RuntimeError, match="fault injection"):
        settings.validate_for_startup()
    assert settings.fault_injection_allowed is False


def test_disabled_never_blocks_startup_in_any_environment():
    dev(
        environment=Environment.PRODUCTION,
        supabase_url="https://example.supabase.co",
        supabase_anon_key="anon",
        cors_origins=["https://app.example.com"],
    ).validate_for_startup()


# --- Qué se puede armar
# -----------------------------------------------------------------------------------------------------------


def test_the_allow_list_is_closed_and_has_no_money_and_no_synthesis():
    assert ALLOWED_TASKS == {
        "product_validation": "market_validation",
        "supplier_sourcing": "supplier_sourcing",
        "legal_validation": "legal_validation",
    }


@pytest.mark.parametrize(
    "task_name", ["finance_validation", "decision_synthesis", "nope", "", "product_*", "*", "product_validation "]
)
def test_F_G_H_a_task_outside_the_allow_list_is_refused(task_name):
    injector = FaultInjector()
    with pytest.raises(ValidationError):
        armed(injector, task_name=task_name)
    assert injector.armed() == []


@pytest.mark.parametrize("attempt", [0, -1, 4, 99])
def test_the_attempt_has_to_be_a_real_one(attempt):
    with pytest.raises(ValidationError):
        armed(FaultInjector(), attempt=attempt)


@pytest.mark.parametrize("objective_id", ["", "  ", "*", "%"])
def test_the_objective_has_to_be_named_exactly(objective_id):
    with pytest.raises(ValidationError):
        armed(FaultInjector(), objective_id=objective_id)


def test_only_one_fault_can_be_armed_at_a_time():
    injector = FaultInjector()
    armed(injector)
    with pytest.raises(ConflictError):
        armed(injector, task_name="legal_validation")
    assert len(injector.armed()) == 1


def test_arming_records_who_when_and_for_how_long():
    clock = Clock()
    fault = armed(FaultInjector(clock), armed_by="owner-7")
    assert (fault.objective_id, fault.task_name, fault.attempt, fault.armed_by) == (
        "obj-1",
        "product_validation",
        1,
        "owner-7",
    )
    assert fault.armed_at == NOW
    assert fault.expires_at == NOW + FAULT_TTL == NOW + datetime.timedelta(minutes=30)
    assert fault.correlation_id == "corr-1"


# --- Disparo: exacto, de un solo uso, consumido ANTES de lanzar
# ------------------------------------------------------------------


def test_L_an_exact_match_fails_once():
    injector = FaultInjector()
    armed(injector)
    first = injector.check(task(), allowed=True)
    assert isinstance(first, InjectedFault)
    assert injector.check(task(), allowed=True) is None  # M: lo siguiente es el agente de verdad
    assert injector.armed() == []


def test_the_fault_is_consumed_before_it_is_raised():
    """`check` devuelve la excepción ya consumida: si algo la lanza tarde o nunca, el armado no sigue vivo."""
    injector = FaultInjector()
    armed(injector)
    fault = injector.check(task(), allowed=True)
    assert fault is not None
    assert injector.armed() == []


@pytest.mark.parametrize(
    "other",
    [
        {"name": "supplier_sourcing", "capability": "supplier_sourcing"},  # I: otra tarea
        {"objective_id": "obj-2"},  # J: otro objetivo
        {"retry_count": 1},  # K: otro intento
        {"objective_id": None},  # una tarea que no es de una misión
    ],
)
def test_I_J_K_anything_that_is_not_the_exact_triple_does_not_fire_and_stays_armed(other):
    injector = FaultInjector()
    armed(injector)
    assert injector.check(task(**other), allowed=True) is None
    assert len(injector.armed()) == 1


def test_an_allowed_name_with_a_capability_outside_the_list_never_fires():
    injector = FaultInjector()
    armed(injector)
    assert injector.check(task(capability="financial_validation"), allowed=True) is None


def test_the_fault_names_the_attempt_that_the_task_is_about_to_make():
    injector = FaultInjector()
    armed(injector, attempt=2)
    assert injector.check(task(retry_count=0), allowed=True) is None
    fault = injector.check(task(retry_count=1), allowed=True)
    assert fault is not None and fault.armed.attempt == 2


def test_disabled_settings_never_fire_and_leave_nothing_armed():
    injector = FaultInjector()
    armed(injector)
    assert injector.check(task(), allowed=False) is None
    assert injector.armed() == []


def test_with_nothing_armed_the_check_is_a_no_op():
    assert FaultInjector().check(task(), allowed=True) is None


# --- La excepción -------------------------------------------------------------------------------------------


def test_S_the_injected_fault_says_it_is_not_retried_inline_and_carries_no_user_data():
    injector = FaultInjector()
    armed(injector, armed_by="owner-1")
    fault = injector.check(task(), allowed=True)
    assert fault is not None
    assert fault.inline_retry is False
    assert isinstance(fault, RuntimeError)
    assert str(fault) == "injected fault (test only)"
    payload = fault.audit_after()
    assert payload["armed_by"] == "owner-1"
    assert {"objective_id", "task", "attempt", "armed_at", "fired_at", "armed_correlation_id"} <= set(payload)
    assert "owner" not in str(fault)


# --- Expiración ---------------------------------------------------------------------------------------------


def test_O_an_expired_fault_does_not_fire():
    clock = Clock()
    injector = FaultInjector(clock)
    armed(injector)
    clock.advance(minutes=30, seconds=1)
    assert injector.check(task(), allowed=True) is None
    assert injector.armed() == []


def test_a_fault_is_still_valid_until_its_expiry_instant():
    clock = Clock()
    injector = FaultInjector(clock)
    armed(injector)
    clock.advance(minutes=29, seconds=59)
    assert injector.check(task(), allowed=True) is not None


def test_R_an_expired_fault_is_reported_once_and_leaves_no_state():
    clock = Clock()
    injector = FaultInjector(clock)
    fault = armed(injector)
    assert injector.take_expired() == []
    clock.advance(minutes=31)
    injector.purge_expired()
    assert injector.take_expired() == [fault]
    assert injector.take_expired() == []
    assert injector.armed() == []


def test_a_fault_that_fired_is_not_reported_as_expired():
    clock = Clock()
    injector = FaultInjector(clock)
    armed(injector)
    injector.check(task(), allowed=True)
    clock.advance(hours=2)
    injector.purge_expired()
    assert injector.take_expired() == []


def test_after_expiry_a_new_fault_can_be_armed():
    clock = Clock()
    injector = FaultInjector(clock)
    armed(injector)
    clock.advance(minutes=31)
    armed(injector, task_name="legal_validation")
    assert [f.task_name for f in injector.armed()] == ["legal_validation"]


# --- Reinicio -----------------------------------------------------------------------------------------------


def test_N_a_new_process_has_nothing_armed():
    injector = FaultInjector()
    armed(injector)
    restarted = FaultInjector()  # otro proceso: el estado vivía solo en la memoria del anterior
    assert restarted.armed() == []
    assert restarted.check(task(), allowed=True) is None


def test_the_process_wide_injector_can_be_replaced_and_starts_empty():
    previous = get_fault_injector()
    try:
        fresh = set_fault_injector(FaultInjector())
        assert get_fault_injector() is fresh
        assert fresh.armed() == []
    finally:
        set_fault_injector(previous)
