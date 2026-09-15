from app.ceo.planner import plan_product_validation
from app.ceo.schemas import Objective


def test_plan_produces_the_expected_task_graph():
    objective = Objective(id="obj-1", title="Validate wireless earbuds opportunity")

    plan = plan_product_validation(objective)

    tasks_by_name = {t.name: t for t in plan.tasks}
    assert set(tasks_by_name) == {
        "product_validation",
        "supplier_sourcing",
        "finance_validation",
        "legal_validation",
        "decision_synthesis",
    }

    assert tasks_by_name["product_validation"].capability == "market_validation"
    assert tasks_by_name["product_validation"].depends_on == []

    assert tasks_by_name["supplier_sourcing"].capability == "supplier_sourcing"
    assert tasks_by_name["supplier_sourcing"].depends_on == ["product_validation"]

    assert tasks_by_name["legal_validation"].capability == "legal_validation"
    assert tasks_by_name["legal_validation"].depends_on == ["product_validation"]

    assert tasks_by_name["finance_validation"].capability == "financial_validation"
    assert set(tasks_by_name["finance_validation"].depends_on) == {"product_validation", "supplier_sourcing"}

    assert tasks_by_name["decision_synthesis"].capability == "decision_synthesis"
    assert set(tasks_by_name["decision_synthesis"].depends_on) == {
        "product_validation",
        "supplier_sourcing",
        "finance_validation",
        "legal_validation",
    }


def test_plan_is_deterministic_for_the_same_objective():
    objective = Objective(id="obj-1", title="Validate wireless earbuds opportunity")

    first = plan_product_validation(objective)
    second = plan_product_validation(objective)

    assert [t.name for t in first.tasks] == [t.name for t in second.tasks]
    assert [t.depends_on for t in first.tasks] == [t.depends_on for t in second.tasks]


def test_plan_project_name_derives_from_objective_title():
    objective = Objective(id="obj-1", title="Validate wireless earbuds opportunity")

    plan = plan_product_validation(objective)

    assert plan.project_name == "Validate wireless earbuds opportunity"
