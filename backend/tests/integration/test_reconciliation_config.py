"""La configuración de la reconciliación y su validación de arranque (Milestone 45, ADR 0029 §3 y §9).

Lo que se afirma:

- todo es configurable y los valores iniciales son los aprobados por el propietario; los límites inválidos no arrancan;
- `external_call_max_seconds` **no tiene valor por defecto** fuera de la simulación: con un proveedor de escritura no
simulado hay que configurarlo, y el
  adaptador tiene que declarar su timeout efectivo sin superarlo; el umbral del barrido tiene que superar el techo
  con margen;
- el valor de 120 s es **provisional y no contractual**: solo existe mientras todo lo que escribe es simulado, y se
informa de que lo es;
- la API y los workers hacen la comprobación al arrancar.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as SettingsError

from app.core.config import PROVISIONAL_EXTERNAL_CALL_MAX_SECONDS, Settings
from app.integrations.ports import ProviderKind
from app.integrations.registry import ProviderNotAvailableError
from app.jobs.queue import DEFAULT_LEASE_SECONDS
from app.reconciliation.config_check import (
    ReconciliationConfigError,
    validate_reconciliation,
    validate_reconciliation_for_startup,
)

APP = Path(__file__).resolve().parents[2] / "app"


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def real_writer(**overrides) -> Settings:
    return settings(payments_provider=ProviderKind.REAL, **overrides)


def adapter(max_call_seconds) -> SimpleNamespace:
    return SimpleNamespace(max_call_seconds=max_call_seconds)


# --- Los valores y sus límites
# ------------------------------------------------------------------------------------------------


def test_the_initial_values_are_the_ones_the_owner_approved_and_all_are_configurable():
    s = settings()

    assert s.reconciliation_enabled is True
    assert (s.reconcile_actions_interval_seconds, s.reconcile_actions_older_than_minutes) == (300, 15)
    assert (s.reconcile_events_interval_seconds, s.reconcile_events_older_than_minutes) == (120, 5)
    assert s.reconcile_event_max_attempts == 5 and s.reconcile_tick_retention_days == 7
    tuned = settings(
        reconcile_actions_interval_seconds=600,
        reconcile_actions_older_than_minutes=30,
        reconcile_events_interval_seconds=60,
        reconcile_events_older_than_minutes=2,
        reconcile_event_max_attempts=9,
        reconciliation_enabled=False,
    )
    assert (tuned.reconcile_actions_interval_seconds, tuned.reconcile_actions_older_than_minutes) == (600, 30)
    assert (tuned.reconcile_events_interval_seconds, tuned.reconcile_events_older_than_minutes) == (60, 2)
    assert tuned.reconcile_event_max_attempts == 9 and tuned.reconciliation_enabled is False


@pytest.mark.parametrize(
    "override",
    [
        {"reconcile_actions_interval_seconds": 29},
        {"reconcile_events_interval_seconds": 0},
        {"reconcile_actions_older_than_minutes": 0},
        {"reconcile_events_older_than_minutes": 0},
        {"reconcile_event_max_attempts": 0},
        {"reconcile_tick_retention_days": 0},
        {"external_call_max_seconds": 0},
        {"external_call_max_seconds": -5},
    ],
)
def test_a_value_out_of_range_does_not_start(override):
    with pytest.raises(SettingsError):
        settings(**override)


# --- El techo de una llamada externa
# ------------------------------------------------------------------------------------------


def test_the_ceiling_has_no_value_of_its_own_and_the_provisional_one_is_only_for_simulated_writers():
    simulated = settings()

    assert simulated.external_call_max_seconds is None, "nothing is configured: the owner fixed no figure"
    assert simulated.write_providers_are_simulated is True
    assert simulated.effective_external_call_max_seconds == PROVISIONAL_EXTERNAL_CALL_MAX_SECONDS == 120

    assert real_writer().write_providers_are_simulated is False
    assert real_writer().effective_external_call_max_seconds is None, "no provisional value outside the simulation"
    assert real_writer(external_call_max_seconds=45).effective_external_call_max_seconds == 45
    assert settings(external_call_max_seconds=45).effective_external_call_max_seconds == 45, "configured always wins"


@pytest.mark.parametrize(
    "writer", ["payments_provider", "fulfilment_provider", "ads_provider", "marketplaces_provider"]
)
def test_any_non_simulated_write_provider_requires_the_ceiling(writer):
    s = settings(**{writer: ProviderKind.REAL})

    assert s.write_providers_are_simulated is False and s.effective_external_call_max_seconds is None
    with pytest.raises(ReconciliationConfigError, match="EXTERNAL_CALL_MAX_SECONDS must be configured explicitly"):
        validate_reconciliation(s, {writer: adapter(30)})


def test_a_read_only_provider_does_not_need_a_ceiling():
    s = settings(product_intelligence_provider=ProviderKind.REAL, regulatory_provider=ProviderKind.REAL)

    assert s.write_providers_are_simulated is True
    validate_reconciliation(s, {})


def test_the_simulated_defaults_pass_the_validation():
    validate_reconciliation(settings(), {})
    validate_reconciliation_for_startup(settings())


# --- El adaptador declara su timeout efectivo
# -----------------------------------------------------------------------------------


def test_a_real_adapter_must_declare_its_effective_timeout_and_not_exceed_the_ceiling():
    s = real_writer(external_call_max_seconds=60)

    validate_reconciliation(s, {"payments": adapter(60)})
    validate_reconciliation(s, {"payments": adapter(1)})
    for bad in (None, 0, -1, True, "30", 61, 600):
        with pytest.raises(ReconciliationConfigError, match="payments"):
            validate_reconciliation(s, {"payments": adapter(bad)})
    with pytest.raises(ReconciliationConfigError, match="payments"):
        validate_reconciliation(s, {"payments": SimpleNamespace()})


def test_every_problem_is_reported_together():
    s = real_writer(external_call_max_seconds=60)

    with pytest.raises(ReconciliationConfigError) as raised:
        validate_reconciliation(s, {"payments": adapter(None), "fulfilment": adapter(900)})

    message = str(raised.value)
    assert "payments must declare" in message and "fulfilment declares a call timeout of 900s" in message


# --- El umbral del barrido supera el techo con margen
# -------------------------------------------------------------------------


def test_the_threshold_must_exceed_twice_the_ceiling_plus_the_job_lease():
    boundary = (15 * 60 - DEFAULT_LEASE_SECONDS) // 2  # 420 s con los valores iniciales

    validate_reconciliation(settings(external_call_max_seconds=boundary))
    with pytest.raises(ReconciliationConfigError, match=r"must be at least 2 x the external call ceiling"):
        validate_reconciliation(settings(external_call_max_seconds=boundary + 1))


def test_a_longer_threshold_allows_a_longer_ceiling():
    validate_reconciliation(settings(external_call_max_seconds=900, reconcile_actions_older_than_minutes=40))
    with pytest.raises(ReconciliationConfigError):
        validate_reconciliation(settings(external_call_max_seconds=900, reconcile_actions_older_than_minutes=20))


def test_the_message_names_the_numbers_so_the_operator_can_fix_it():
    with pytest.raises(ReconciliationConfigError) as raised:
        validate_reconciliation(settings(external_call_max_seconds=600))

    message = str(raised.value)
    assert "900s" in message and "600s" in message and "1260s" in message and "legitimately in flight" in message


def test_with_the_reconciliation_disabled_the_threshold_is_not_checked_but_a_real_adapter_still_is():
    off = settings(reconciliation_enabled=False, external_call_max_seconds=5000)
    validate_reconciliation(off, {})

    with pytest.raises(ReconciliationConfigError, match="declare"):
        validate_reconciliation(
            real_writer(reconciliation_enabled=False, external_call_max_seconds=60), {"payments": adapter(None)}
        )


# --- El arranque ----------------------------------------------------------------------------------------------------


def test_the_startup_check_resolves_the_real_write_adapters_and_fails_when_they_do_not_exist_yet():
    with pytest.raises(ProviderNotAvailableError):
        validate_reconciliation_for_startup(real_writer(external_call_max_seconds=60))


def test_the_api_and_every_worker_run_the_check_at_startup():
    assert "validate_reconciliation_for_startup(settings)" in (APP / "main.py").read_text(encoding="utf-8")
    worker = (APP / "jobs" / "worker.py").read_text(encoding="utf-8")
    assert "validate_reconciliation_for_startup(get_settings())" in worker
    assert worker.index("validate_reconciliation_for_startup") < worker.index("worker = Worker(")


def test_a_worker_with_an_unsustainable_configuration_does_not_start(monkeypatch):
    from app.jobs import worker as worker_module
    from app.reconciliation import config_check

    def refuse(_settings):
        raise ReconciliationConfigError("invalid reconciliation configuration: test")

    monkeypatch.setattr(config_check, "validate_reconciliation_for_startup", refuse)

    def no_loop(*args, **kwargs):
        raise AssertionError("the worker must refuse before it ever runs")

    monkeypatch.setattr(worker_module.Worker, "run_forever", no_loop)
    monkeypatch.setattr(worker_module.Worker, "run_once", no_loop)

    with pytest.raises(ReconciliationConfigError):
        worker_module.main(["--once"])


def test_no_figure_of_120_seconds_hides_in_the_code_as_a_threshold():
    """Ninguna lógica depende de 120 s: el techo sale de la configuración y el valor provisional solo se declara en
    `config.py`."""
    hard_coded = []
    for path in (APP / "reconciliation").glob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if re.search(r"(?<![\w.])120(?![\w.])", code) and "http" not in code:
                hard_coded.append(f"{path.name}:{number}")
    assert hard_coded == []
