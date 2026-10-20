import pytest

from app.agents.base import AgentResultStatus
from app.agents.cfo import CFOAgent


def _base_input(**overrides):
    payload = {
        "total_products_analyzed": 10,
        "go_count": 8,
        "review_count": 1,
        "no_go_count": 1,
        "total_campaigns": 5,
        "active_campaigns": 4,
        "total_daily_budget": 200.0,
        "total_budget_hard_limit": 1000.0,
        "total_reserved": 100.0,
        "total_committed": 50.0,
        "total_spent": 50.0,
    }
    payload.update(overrides)
    return payload


def test_empty_catalog_needs_review():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=0, go_count=0, review_count=0, no_go_count=0))

    assert result.status == AgentResultStatus.COMPLETED
    assert result.data["financial_health_status"] == "NEEDS_REVIEW"
    assert result.recommendation == "REVIEW"
    assert any("insufficient data" in risk for risk in result.risks)


def test_healthy_mix_is_healthy():
    agent = CFOAgent()

    result = agent.run(_base_input())

    assert result.data["financial_health_status"] == "HEALTHY"
    assert result.recommendation == "GO"


def test_majority_no_go_is_critical():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=10, go_count=2, review_count=2, no_go_count=6))

    assert result.data["financial_health_status"] == "CRITICAL"
    assert result.recommendation == "NO_GO"
    assert any("risk concentration" in risk for risk in result.risks)


def test_elevated_no_go_ratio_is_at_risk():
    agent = CFOAgent()

    result = agent.run(_base_input(total_products_analyzed=10, go_count=6, review_count=1, no_go_count=3))

    assert result.data["financial_health_status"] == "AT_RISK"
    assert result.recommendation == "REVIEW"


def test_high_budget_utilization_is_at_risk():
    agent = CFOAgent()

    # 500 reservados + 450 comprometidos = 950 de 1000: 95 % (lo gastado, 450, ya está dentro de lo comprometido).
    result = agent.run(
        _base_input(total_reserved=500.0, total_committed=450.0, total_spent=450.0, total_budget_hard_limit=1000.0)
    )

    assert result.data["financial_health_status"] == "AT_RISK"
    assert result.data["budget_utilization"] == pytest.approx(0.95)
    assert any("budget utilization" in risk for risk in result.risks)
    assert any("95%" in risk for risk in result.risks)


def test_no_budget_recorded_flags_the_assumption():
    agent = CFOAgent()

    result = agent.run(_base_input(total_budget_hard_limit=0, total_reserved=0, total_committed=0, total_spent=0))

    assert result.data["budget_utilization"] is None
    assert any("no budget allocations recorded" in risk for risk in result.risks)


# --- El contrato del uso del presupuesto (M47) ------------------------------------------------------------------------
#
# Uso = reservado + comprometido, sobre el techo. Lo gastado se informa aparte y NO se suma: un COMMIT ya lo mueve a
# `committed` y a `spent` a la vez, y sumarlo otra vez contaba el gasto dos veces (lo mismo que
# `remaining = hard_limit - reserved - committed` de `GET /api/budget`, que no resta `spent`).


def _utilization(hard_limit, reserved, committed, spent):
    result = CFOAgent().run(
        _base_input(
            total_budget_hard_limit=hard_limit, total_reserved=reserved, total_committed=committed, total_spent=spent
        )
    )
    return result.data["budget_utilization"]


@pytest.mark.parametrize(
    ("hard_limit", "reserved", "committed", "spent", "expected"),
    [
        (100.0, 0.0, 0.0, 0.0, 0.0),  # A
        (100.0, 25.0, 0.0, 0.0, 0.25),  # B
        (100.0, 0.0, 40.0, 40.0, 0.40),  # C: NO 0,80
        (100.0, 25.0, 40.0, 40.0, 0.65),  # D: NO 1,05
        (1.0, 0.0, 1.0, 1.0, 1.0),  # E: el presupuesto real tras la segunda misión; NO 2,00
        (100.0, 0.0, 50.0, 50.0, 0.5),
        (1000.0, 100.0, 50.0, 50.0, 0.15),
    ],
)
def test_utilization_is_reserved_plus_committed_over_the_ceiling(hard_limit, reserved, committed, spent, expected):
    assert _utilization(hard_limit, reserved, committed, spent) == pytest.approx(expected)


@pytest.mark.parametrize("spent", [0.0, 7.0, 40.0, 500.0, 99999.0])
def test_utilization_does_not_depend_on_spent(spent):
    """G y H: con `spent` distinto de `committed`, y cambiando `spent` con reservado y comprometido fijos, el uso no
    se mueve."""
    assert _utilization(100.0, 25.0, 40.0, spent) == pytest.approx(0.65)


@pytest.mark.parametrize("hard_limit", [0.0, -1.0, -100.0])
def test_without_a_positive_ceiling_there_is_no_utilization_and_no_invented_division(hard_limit):
    """F: el contrato de siempre. Sin techo (o con uno no positivo) el uso es `None`, no una división inventada."""
    result = CFOAgent().run(
        _base_input(total_budget_hard_limit=hard_limit, total_reserved=5.0, total_committed=5.0, total_spent=5.0)
    )

    assert result.data["budget_utilization"] is None
    assert any("no budget allocations recorded" in risk for risk in result.risks)


def test_half_the_budget_committed_is_not_at_risk_because_of_the_budget():
    """El ejemplo del contrato: techo 100, comprometido 50, gastado 50 ⇒ uso 0,50 y NO «En riesgo» por presupuesto
    (antes: 1,00)."""
    result = CFOAgent().run(
        _base_input(total_budget_hard_limit=100.0, total_reserved=0.0, total_committed=50.0, total_spent=50.0)
    )

    assert result.data["budget_utilization"] == pytest.approx(0.5)
    assert result.data["financial_health_status"] == "HEALTHY"
    assert not any("budget utilization" in risk for risk in result.risks)


def test_a_lot_of_spent_with_little_reserved_and_committed_is_not_at_risk():
    result = CFOAgent().run(
        _base_input(total_budget_hard_limit=100.0, total_reserved=10.0, total_committed=10.0, total_spent=95.0)
    )

    assert result.data["budget_utilization"] == pytest.approx(0.2)
    assert result.data["financial_health_status"] == "HEALTHY"


@pytest.mark.parametrize(
    ("committed", "status"),
    [(89.0, "HEALTHY"), (90.0, "HEALTHY"), (91.0, "AT_RISK"), (100.0, "AT_RISK")],
)
def test_the_threshold_is_still_above_ninety_percent_of_reserved_plus_committed(committed, status):
    """El umbral no cambia (0,9, estrictamente por encima); lo que cambia es el valor al que se aplica."""
    result = CFOAgent().run(
        _base_input(total_budget_hard_limit=100.0, total_reserved=0.0, total_committed=committed, total_spent=committed)
    )

    assert result.data["financial_health_status"] == status


def test_spent_is_still_reported_in_the_data():
    result = CFOAgent().run(_base_input(total_spent=33.0))

    assert result.data["total_spent"] == 33.0
    assert result.data["total_committed"] == 50.0
    assert result.data["total_reserved"] == 100.0


def test_the_budget_risk_names_the_correct_percentage():
    result = CFOAgent().run(
        _base_input(total_budget_hard_limit=100.0, total_reserved=25.0, total_committed=70.0, total_spent=70.0)
    )

    assert result.data["financial_health_status"] == "AT_RISK"
    assert any("95%" in risk for risk in result.risks), result.risks


def test_a_budget_risk_is_only_listed_above_ninety_percent_even_when_the_status_is_at_risk_for_another_reason():
    """«En riesgo» por NO_GO con un uso moderado (60 %) no añade un aviso de presupuesto: ese aviso es solo para más
    del 90 %."""
    result = CFOAgent().run(
        _base_input(
            total_products_analyzed=10,
            go_count=6,
            review_count=1,
            no_go_count=3,
            total_budget_hard_limit=100.0,
            total_reserved=20.0,
            total_committed=40.0,
            total_spent=40.0,
        )
    )

    assert result.data["financial_health_status"] == "AT_RISK"
    assert result.data["budget_utilization"] == pytest.approx(0.6)
    assert any("elevated risk concentration" in risk for risk in result.risks)
    assert not any("budget utilization" in risk for risk in result.risks), result.risks
