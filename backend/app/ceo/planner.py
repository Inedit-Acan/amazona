from app.ceo.schemas import Objective, ProjectPlan, TaskSpec


def plan_product_validation(objective: Objective) -> ProjectPlan:
    """Deterministically decompose a product-validation objective into the
    Milestone 1 task graph: Product -> {Supplier, Legal} -> Finance -> Decision.

    Finance depends on both Product and Supplier because landed cost
    (unit cost + logistics) comes from supplier sourcing.
    """
    tasks = [
        TaskSpec(name="product_validation", capability="market_validation"),
        TaskSpec(
            name="supplier_sourcing",
            capability="supplier_sourcing",
            depends_on=["product_validation"],
        ),
        TaskSpec(
            name="legal_validation",
            capability="legal_validation",
            depends_on=["product_validation"],
        ),
        TaskSpec(
            name="finance_validation",
            capability="financial_validation",
            depends_on=["product_validation", "supplier_sourcing"],
        ),
        TaskSpec(
            name="decision_synthesis",
            capability="decision_synthesis",
            depends_on=["product_validation", "supplier_sourcing", "finance_validation", "legal_validation"],
        ),
    ]

    return ProjectPlan(project_name=objective.title, tasks=tasks)
