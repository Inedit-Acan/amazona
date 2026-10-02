"""La política operativa de un proveedor (Milestone 44, ADR 0028 §7).

Responde **qué operaciones externas declara soportar** un adaptador. No responde qué se puede hacer con sus datos:
eso es `usage_rights`, y esta prueba comprueba que las dos cosas no se mezclan.
"""

import ast
from pathlib import Path

import pytest

from app.core.config import Environment, Settings
from app.integrations import operating_policy, usage_rights
from app.integrations.operating_policy import (
    OPERATING_POLICIES,
    UNREGISTERED,
    CostModel,
    OperationNotPermittedError,
    policy_for,
    require_operation,
)

APP = Path(__file__).resolve().parents[2] / "app"


def test_a_provider_nobody_wrote_down_declares_no_operation():
    policy = policy_for("some-real-psp")

    assert policy is UNREGISTERED
    assert policy.operations == {}
    with pytest.raises(OperationNotPermittedError, match="does not declare"):
        require_operation("some-real-psp", "payment.open", Settings())


def test_an_operation_the_policy_does_not_declare_is_denied_even_for_a_known_provider():
    with pytest.raises(OperationNotPermittedError, match="payment.teleport"):
        require_operation("simulated-payments", "payment.teleport", Settings())


def test_a_declared_operation_returns_its_policy():
    declared = require_operation("simulated-fulfilment", "fulfillment.purchase", Settings())

    assert declared.cost_model is CostModel.FROM_ORDER_LINES
    assert declared.real_effects is False
    assert (
        require_operation("simulated-fulfilment", "fulfillment.ship", Settings()).cost_model is CostModel.ZERO_SIMULATED
    )


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_a_simulated_adapter_is_not_accepted_where_effects_have_to_be_real(environment):
    for provider, operation in (("simulated-payments", "payment.open"), ("simulated-fulfilment", "fulfillment.ship")):
        with pytest.raises(OperationNotPermittedError, match="simulated"):
            require_operation(provider, operation, Settings(environment=environment))


def test_every_policy_says_where_and_when_it_was_written():
    for policy in OPERATING_POLICIES.values():
        assert policy.source.strip() and policy.verified_on.year >= 2026
        assert policy.operations, policy.provider
        for name, operation in policy.operations.items():
            assert operation.operation == name


def test_every_simulated_adapter_has_both_a_policy_and_a_data_rights_entry_and_they_are_separate_records():
    for provider in ("simulated-payments", "simulated-fulfilment"):
        assert provider in OPERATING_POLICIES
        assert provider in usage_rights.USAGE_RIGHTS
        assert usage_rights.rights_for(provider) is not OPERATING_POLICIES[provider]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_operating_policy_and_usage_rights_do_not_depend_on_each_other():
    """Dos responsabilidades, dos módulos: ninguna es la fuente de verdad de la otra."""
    assert "app.integrations.usage_rights" not in _imported_modules(Path(operating_policy.__file__))
    assert "app.integrations.operating_policy" not in _imported_modules(Path(usage_rights.__file__))
