"""El efecto de una aprobación en el presupuesto y quién figura como actor (corrección tras la primera misión real).

Tres observaciones de la primera misión controlada sobre Supabase:

A. La pantalla decía «el importe pasa de reservado a comprometido en el presupuesto» aunque no había presupuesto (el
   despliegue era simulado y el CEO aprobó el gasto como `simulated_no_budget`: no se reservó nada). La aprobación
   expone ahora `budget_effect`, que sale del LIBRO real (`financial_events`, por la referencia `approval:<id>`) y
   no de una suposición: `none` (ningún movimiento), `reserved` (reservado, sin liquidar), `committed` o `released`.
B. Resolver una aprobación solo cambia la aprobación (`status`, `resolved_at`, `resolved_by`) y su asiento de
   auditoría: NO toca la decisión (`HUMAN_APPROVAL` es el resultado del motor, no un estado de flujo), ni el
   proyecto ni el objetivo (no hay ninguna transición prevista: una aprobación autoriza UNA acción contextual).
   Lo fija una prueba para que un cambio futuro sea deliberado.
C. El cuerpo `{"actor": …}` pasa a ser OPCIONAL. Sin él, el actor es el de la identidad (`local-development` sin
   autenticar, el verificado con token), nunca un correo que nadie ha comprobado; y la auditoría conserva
   `actor_source`.
"""

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import LOCAL_SUBJECT
from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.session import get_db
from app.main import app

UTC = datetime.UTC
T0 = datetime.datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def engine(request):
    if request.param == "sqlite":
        sqlite = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(sqlite)
        yield sqlite
        sqlite.dispose()
    else:
        with ephemeral_postgres() as postgres:
            yield postgres


@pytest.fixture()
def session_factory(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        # El flujo real del CEO deja tareas, evidencias, memoria y ejecuciones: se vacía TODO en orden de dependencias.
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    return factory


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def seed(session_factory):
    """Una aprobación PENDING con su cadena objetivo → proyecto → decisión. Devuelve sus ids."""

    def add(amount: float | None = 1.0, correlation_id: str | None = None) -> dict[str, str]:
        with session_factory() as session:
            objective = Objective(title="obj", created_by="seed", status="RECEIVED")
            session.add(objective)
            session.flush()
            project = Project(objective_id=objective.id, name="proj", status="VALIDATING")
            session.add(project)
            session.flush()
            decision = Decision(project_id=project.id, status="HUMAN_APPROVAL", correlation_id="d" * 36)
            session.add(decision)
            session.flush()
            approval = Approval(
                decision_id=decision.id,
                action="simulated_external_spend",
                amount=amount,
                status="PENDING",
                requested_at=T0,
                expires_at=datetime.datetime.now(UTC) + datetime.timedelta(hours=24),
                correlation_id=correlation_id or str(uuid.uuid4()),
            )
            session.add(approval)
            session.flush()
            ids = {
                "objective": objective.id,
                "project": project.id,
                "decision": decision.id,
                "approval": approval.id,
                "correlation": approval.correlation_id,
            }
            session.commit()
        return ids

    return add


@pytest.fixture()
def authorise(session_factory):
    """El propietario autoriza un presupuesto (`authorise-budget`) y el CEO reserva el importe de UNA aprobación."""

    def go(ids: dict[str, str], *, amount: float = 1.0, hard_limit: float = 50.0) -> None:
        with session_factory() as session:
            ledger = BudgetLedgerService(session)
            ledger.authorise_budget(hard_limit=hard_limit, actor="cli:test")
            assert ledger.reserve(amount=amount, reference=f"approval:{ids['approval']}")
            session.commit()

    return go


def effect_of(client: TestClient, approval_id: str) -> str:
    rows = {row["id"]: row for row in client.get("/api/approvals").json()}
    return rows[approval_id]["budget_effect"]


# --- A · el efecto en el presupuesto sale del libro -----------------------------------------------------------------


def test_without_any_ledger_movement_the_effect_is_none(client, seed):
    ids = seed()
    assert effect_of(client, ids["approval"]) == "none"


def test_a_reservation_in_the_ledger_is_reserved(client, seed, authorise):
    ids = seed()
    authorise(ids)
    assert effect_of(client, ids["approval"]) == "reserved"


def test_the_effect_does_not_depend_on_the_amount_or_on_there_being_a_budget(client, seed):
    big = seed(amount=100000.0)
    zero = seed(amount=0.0)
    unknown = seed(amount=None)
    for ids in (big, zero, unknown):
        assert effect_of(client, ids["approval"]) == "none", "el importe NO implica movimiento de presupuesto"


def test_a_reservation_of_another_approval_does_not_leak(client, seed, authorise):
    reserved = seed()
    other = seed()
    authorise(reserved)
    assert effect_of(client, reserved["approval"]) == "reserved"
    assert effect_of(client, other["approval"]) == "none"


def test_approving_with_a_reservation_commits_it(client, seed, authorise):
    ids = seed()
    authorise(ids)
    response = client.post(f"/api/approvals/{ids['approval']}/approve", json={})
    assert response.status_code == 200
    assert response.json()["budget_effect"] == "committed", "la respuesta de approve lleva el mismo campo"
    assert effect_of(client, ids["approval"]) == "committed"


def test_rejecting_with_a_reservation_releases_it(client, seed, authorise):
    ids = seed()
    authorise(ids)
    response = client.post(f"/api/approvals/{ids['approval']}/reject", json={})
    assert response.status_code == 200
    assert response.json()["budget_effect"] == "released"
    assert effect_of(client, ids["approval"]) == "released"


def test_approving_a_simulated_no_budget_approval_moves_nothing(client, seed, session_factory):
    """El caso de la primera misión: sin presupuesto autorizado el CEO aprobó el gasto simulado y no reservó nada."""
    ids = seed()
    response = client.post(f"/api/approvals/{ids['approval']}/approve", json={})
    assert response.status_code == 200
    assert response.json()["budget_effect"] == "none"
    with session_factory() as session:
        assert session.query(FinancialEvent).count() == 0
        assert session.query(Budget).count() == 0
        assert session.query(BudgetAllocation).count() == 0


def test_budget_effect_is_one_of_the_four_values_and_only_added(client, seed):
    seed()
    row = client.get("/api/approvals").json()[0]
    assert row["budget_effect"] in {"none", "reserved", "committed", "released"}
    assert {"id", "decision_id", "action", "amount", "status", "expires_at", "resolved_at", "resolved_by"} <= set(row)
    assert {"requested_at", "correlation_id"} <= set(row)


# --- B · resolver una aprobación solo cambia la aprobación ----------------------------------------------------------


@pytest.mark.parametrize("verb,status", [("approve", "APPROVED"), ("reject", "REJECTED")])
def test_resolving_changes_only_the_approval(client, seed, session_factory, verb, status):
    ids = seed()
    before = client.get("/api/approvals").json()[0]
    response = client.post(f"/api/approvals/{ids['approval']}/{verb}", json={})
    assert response.status_code == 200
    after = response.json()
    assert after["status"] == status
    assert after["resolved_at"] is not None
    assert after["resolved_by"]
    # lo que NO cambia: cuándo se pidió, su correlación, su acción, su importe y su caducidad
    for field in ("requested_at", "correlation_id", "action", "amount", "expires_at", "decision_id", "id"):
        assert after[field] == before[field], field
    with session_factory() as session:
        decision = session.get(Decision, ids["decision"])
        assert decision.status == "HUMAN_APPROVAL", "la decisión es el resultado del motor"
        assert session.get(Project, ids["project"]).status == "VALIDATING", "no hay transición del proyecto"
        assert session.get(Objective, ids["objective"]).status == "RECEIVED", "no hay transición del objetivo"


def test_the_audit_entry_of_the_resolution_keeps_the_correlation(client, seed, session_factory):
    ids = seed()
    client.post(f"/api/approvals/{ids['approval']}/approve", json={})
    with session_factory() as session:
        entry = session.query(AuditLog).filter_by(action="approval.approve").one()
        assert entry.correlation_id == ids["correlation"]
        assert entry.resource == f"approval:{ids['approval']}"
        assert (entry.before, entry.after) == ({"status": "PENDING"}, {"status": "APPROVED"})


def test_an_approval_is_resolved_once(client, seed):
    ids = seed()
    assert client.post(f"/api/approvals/{ids['approval']}/approve", json={}).status_code == 200
    assert client.post(f"/api/approvals/{ids['approval']}/reject", json={}).status_code == 409


# --- C · el actor ---------------------------------------------------------------------------------------------------


def test_the_body_may_omit_the_actor_and_the_actor_is_the_unverified_local_one(client, seed, session_factory):
    ids = seed()
    response = client.post(f"/api/approvals/{ids['approval']}/approve", json={})
    assert response.status_code == 200
    assert response.json()["resolved_by"] == LOCAL_SUBJECT
    with session_factory() as session:
        entry = session.query(AuditLog).filter_by(action="approval.approve").one()
        assert entry.actor == LOCAL_SUBJECT
        assert entry.actor_source == "declared", "no autenticado: la auditoría lo dice"


def test_no_body_at_all_is_a_validation_error_not_a_silent_default(client, seed):
    ids = seed()
    assert client.post(f"/api/approvals/{ids['approval']}/approve").status_code == 422


def test_a_declared_actor_is_still_honoured_outside_staging_and_production(client, seed, session_factory):
    ids = seed()
    response = client.post(f"/api/approvals/{ids['approval']}/approve", json={"actor": "someone-declared"})
    assert response.json()["resolved_by"] == "someone-declared"
    with session_factory() as session:
        assert session.query(AuditLog).filter_by(action="approval.approve").one().actor_source == "declared"


@pytest.mark.parametrize("body", [{"actor": ""}, {"actor": None}])
def test_an_empty_or_null_actor_is_never_stored_as_empty(client, seed, body):
    ids = seed()
    response = client.post(f"/api/approvals/{ids['approval']}/approve", json=body)
    assert response.status_code == 200
    assert response.json()["resolved_by"] == LOCAL_SUBJECT


@pytest.mark.parametrize("bad", [5, ["a"], {"x": 1}, True])
def test_an_actor_that_is_not_text_is_refused(client, seed, bad):
    ids = seed()
    assert client.post(f"/api/approvals/{ids['approval']}/approve", json={"actor": bad}).status_code == 422


def test_the_audit_api_exposes_where_the_actor_came_from(client, seed):
    ids = seed()
    client.post(f"/api/approvals/{ids['approval']}/approve", json={})
    rows = client.get("/api/audit?order=desc&limit=5").json()
    approve = next(row for row in rows if row["action"] == "approval.approve")
    assert approve["actor_source"] == "declared"
    assert approve["actor"] == LOCAL_SUBJECT
    assert all("actor_source" in row for row in rows)


def test_an_audit_row_without_a_source_has_it_as_null_not_invented(client, session_factory):
    with session_factory() as session:
        session.add(AuditLog(actor="ceo", action="decision.made", resource="decision:x", correlation_id="c" * 36))
        session.commit()
    row = client.get("/api/audit").json()[0]
    assert row["actor"] == "ceo"
    assert row["actor_source"] is None


# --- el flujo REAL del CEO (el que hizo la primera misión), con y sin presupuesto autorizado
# -----------------------------

SPEND_CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
    "requests_simulated_spend": True,
    "spend_action": "simulated_external_spend",
    "spend_amount": 1.0,
}


def run_real_mission(session_factory, *, with_budget: bool) -> str:
    with session_factory() as session:
        if with_budget:
            BudgetLedgerService(session).authorise_budget(hard_limit=50.0, actor="cli:test")
        objective = Objective(title="[PRUEBA] real", created_by="prueba", context=SPEND_CONTEXT)
        session.add(objective)
        session.commit()
        CEOOrchestrator(session).run_objective(objective.id)
        session.commit()
        return session.query(Approval).one().id


def test_the_real_ceo_flow_without_a_budget_reserves_nothing_and_says_so(client, session_factory):
    approval_id = run_real_mission(session_factory, with_budget=False)
    assert effect_of(client, approval_id) == "none"
    with session_factory() as session:
        audit = session.query(AuditLog).filter_by(action="approval.requested").one()
        assert audit.after["budget"] == "simulated_no_budget"
        assert session.query(FinancialEvent).count() == 0
    response = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.json()["budget_effect"] == "none", "aprobar sin presupuesto no compromete nada"


def test_the_real_ceo_flow_with_a_budget_reserves_then_commits(client, session_factory):
    approval_id = run_real_mission(session_factory, with_budget=True)
    assert effect_of(client, approval_id) == "reserved"
    response = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.json()["budget_effect"] == "committed"
    with session_factory() as session:
        decision = session.query(Decision).one()
        assert decision.status == "HUMAN_APPROVAL", "la decisión conserva su resultado"
        assert session.query(Objective).one().status == "RECEIVED"


def test_rejecting_without_an_actor_is_also_the_unverified_local_one(client, seed, session_factory):
    ids = seed()
    response = client.post(f"/api/approvals/{ids['approval']}/reject", json={})
    assert response.status_code == 200
    assert response.json()["resolved_by"] == LOCAL_SUBJECT
    with session_factory() as session:
        entry = session.query(AuditLog).filter_by(action="approval.reject").one()
        assert (entry.actor, entry.actor_source) == (LOCAL_SUBJECT, "declared")


# --- La referencia del libro es NULLABLE: la rama «sin referencia» ----------------------------------------------------
# `financial_events.reference` admite NULL (un movimiento sin referencia). Ningún movimiento SIN referencia pertenece
# a una aprobación, así que se ignora de forma explícita; la consulta ya lo excluye (`NULL LIKE …` no es verdadero),
# pero el tipo de la columna es `str | None` y el contrato se maneja a la vista, no se supone.


def test_events_without_a_reference_are_ignored_and_those_with_one_are_read():
    from app.api.approvals import _effects_from_events

    events = [
        (None, "RESERVE"),
        ("approval:a", "RESERVE"),
        (None, "COMMIT"),
        ("approval:b", "RESERVE"),
        ("approval:b", "COMMIT"),
        (None, "RELEASE"),
        ("approval:c", "RESERVE"),
        ("approval:c", "RELEASE"),
    ]
    assert _effects_from_events(events) == {"a": "reserved", "b": "committed", "c": "released"}


def test_only_events_without_a_reference_give_no_effect_at_all():
    from app.api.approvals import _effects_from_events

    assert _effects_from_events([(None, "RESERVE"), (None, "COMMIT"), (None, "RELEASE")]) == {}
    assert _effects_from_events([]) == {}


def test_a_ledger_event_with_a_null_reference_does_not_change_any_approval(client, seed, session_factory):
    ids = seed()
    with session_factory() as session:
        session.add(FinancialEvent(type="COMMIT", amount=1.0, reference=None))
        session.commit()
    assert effect_of(client, ids["approval"]) == "none"


def test_a_null_reference_event_does_not_hide_a_real_reservation(client, seed, authorise, session_factory):
    ids = seed()
    authorise(ids)
    with session_factory() as session:
        session.add(FinancialEvent(type="RELEASE", amount=1.0, reference=None))
        session.commit()
    assert effect_of(client, ids["approval"]) == "reserved"
