"""`POST /api/tasks/{id}/retry` y `POST /api/tasks/{id}/reassign`, y `recovery` en `GET /api/tasks` (M49, Commit 8).

Solo dos rutas nuevas (no había ningún mecanismo para esto), con contrato estricto: el reintento nombra el intento
que repite (`after_attempt`), la reasignación nombra un agente del registro y un motivo. Ninguna tiene efectos
implícitos: reasignar no ejecuta, reintentar no reasigna ni arrastra a los dependientes."""

import pytest
from fastapi.testclient import TestClient
from recovery_test_support import Scripted, build_manager, executions_of, run_mission, tasks_by_name
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.base import AgentStatus
from app.api.tasks import get_agent_manager
from app.auth.actor import RoleName
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.project import Project
from app.db.session import get_db
from app.main import app
from app.permissions.policies import ApiAction, role_can

P1, P2 = "agent-product-1", "agent-product-2"


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        yield session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_agent_manager, None)
        engine.dispose()


@pytest.fixture()
def client(factory) -> TestClient:
    return TestClient(app)


def failed_mission(factory, script, *, second=None, max_task_retries=1):
    """Una misión cuyo agente de producto sigue `script`. Devuelve (manager, project_id, task_id de producto)."""
    agents = {P1: Scripted(script), **({P2: second} if second is not None else {})}
    _, manager = build_manager(agents)
    app.dependency_overrides[get_agent_manager] = lambda: manager
    with factory() as db:
        run_mission(db, manager, max_task_retries=max_task_retries)
        project_id = db.query(Project).one().id
        return manager, project_id, tasks_by_name(db)["product_validation"].id


def task_of(client, project_id, name):
    return {t["name"]: t for t in client.get("/api/tasks", params={"project_id": project_id}).json()}[name]


def test_only_two_new_routes_exist_and_both_are_post():
    paths = app.openapi()["paths"]
    assert set(paths["/api/tasks/{task_id}/retry"]) == {"post"}
    assert set(paths["/api/tasks/{task_id}/reassign"]) == {"post"}
    assert set(paths["/api/tasks"]) == {"get"}


def test_retry_runs_the_next_attempt_and_returns_the_task_with_its_relation(client, factory):
    _, project_id, task_id = failed_mission(factory, [False, False, True])

    response = client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2, "reason": "network blip"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["assigned_agent_id"] == P1
    relation = body["agent_relation"]
    assert relation["status"] == "MATCH"
    assert [(e["attempt"], e["success"], e["agent_id"]) for e in relation["executions"]] == [
        (1, False, P1),
        (2, False, P1),
        (3, True, P1),
    ]
    assert body["recovery"]["kind"] == "none"
    # y lo que desbloquea queda pendiente, NO ejecutado
    assert task_of(client, project_id, "supplier_sourcing")["status"] == "PENDING"
    assert task_of(client, project_id, "supplier_sourcing")["agent_relation"]["executions"] == []


def test_retry_that_fails_again_still_answers_200_with_the_failed_task(client, factory):
    _, _, task_id = failed_mission(factory, [False, False, False])

    response = client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2})

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert len(response.json()["agent_relation"]["executions"]) == 3
    assert response.json()["recovery"]["kind"] == "reassign_required"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"after_attempt": 0},
        {"after_attempt": -1},
        {"after_attempt": "dos"},
        {"after_attempt": 1, "extra": 1},
        {"after_attempt": 1, "reason": "x" * 501},
    ],
)
def test_retry_has_a_strict_body(client, factory, payload):
    _, _, task_id = failed_mission(factory, [False, False])

    response = client.post(f"/api/tasks/{task_id}/retry", json=payload)

    assert response.status_code == 422
    with factory() as db:
        assert [r.attempt for r in executions_of(db, tasks_by_name(db)["product_validation"])] == [1, 2]


def test_retry_errors_are_404_for_unknown_and_409_for_state(client, factory):
    _, project_id, task_id = failed_mission(factory, [False, False, True])

    assert client.post("/api/tasks/nope/retry", json={"after_attempt": 1}).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 1}).status_code == 409  # intento viejo
    supplier = task_of(client, project_id, "supplier_sourcing")
    assert client.post(f"/api/tasks/{supplier['id']}/retry", json={"after_attempt": 1}).status_code == 409  # BLOQUEADA
    assert client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 3}).status_code == 409  # ya COMPLETED


def test_retry_with_an_idempotency_key_is_executed_once(client, factory):
    _, project_id, task_id = failed_mission(factory, [False, False, True])
    headers = {"Idempotency-Key": "retry-product-attempt-3-0001"}

    first = client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2}, headers=headers)
    second = client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2}, headers=headers)

    assert first.status_code == second.status_code == 200
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert second.json() == first.json()
    with factory() as db:
        assert [r.attempt for r in executions_of(db, tasks_by_name(db)["product_validation"])] == [1, 2, 3]


def test_reassign_changes_the_assignment_does_not_execute_and_is_audited(client, factory):
    _, project_id, task_id = failed_mission(factory, [False, False], second=Scripted([]))

    response = client.post(
        f"/api/tasks/{task_id}/reassign", json={"agent_id": P2, "reason": "agent-product-1 keeps failing"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["assigned_agent_id"] == P2
    assert body["status"] == "FAILED"
    assert len(body["agent_relation"]["executions"]) == 2  # nada nuevo
    assert body["agent_relation"]["reassigned"] is True
    assert body["recovery"]["kind"] == "recoverable"  # el agente nuevo empieza con sus intentos
    with factory() as db:
        event = db.query(AuditLog).filter_by(action="task.reassigned", resource=f"task:{task_id}").one()
        assert event.before == {"agent_id": P1}
        assert event.after["agent_id"] == P2
        assert event.actor  # quien lo pidió, no un agente
        assert event.actor not in (P1, P2)


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"agent_id": "agent-ghost-9", "reason": "x" * 5}, 422),
        ({"agent_id": "agent-supplier-1", "reason": "x" * 5}, 422),
        ({"agent_id": P1, "reason": "x" * 5}, 422),
        ({"agent_id": P2}, 422),
        ({"agent_id": P2, "reason": ""}, 422),
        ({"reason": "no agent"}, 422),
        ({"agent_id": P2, "reason": "ok ok", "extra": 1}, 422),
    ],
)
def test_reassign_refuses_unknown_incompatible_same_or_malformed(client, factory, payload, status):
    _, _, task_id = failed_mission(factory, [False, False], second=Scripted([]))

    response = client.post(f"/api/tasks/{task_id}/reassign", json=payload)

    assert response.status_code == status
    with factory() as db:
        assert tasks_by_name(db)["product_validation"].assigned_agent_id == P1
        assert not db.query(AuditLog).filter_by(action="task.reassigned").count()


def test_reassign_to_the_orchestrator_task_or_a_completed_one_is_refused(client, factory):
    _, project_id, task_id = failed_mission(factory, [False, False], second=Scripted([]))
    synthesis = task_of(client, project_id, "decision_synthesis")

    assert (
        client.post(f"/api/tasks/{synthesis['id']}/reassign", json={"agent_id": P2, "reason": "no way"}).status_code
        == 422
    )
    client.post(f"/api/tasks/{task_id}/reassign", json={"agent_id": P2, "reason": "switch to 2"})
    assert client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2}).status_code == 200
    assert client.post(f"/api/tasks/{task_id}/reassign", json={"agent_id": P1, "reason": "too late"}).status_code == 409


def test_recovery_in_the_listing_tells_the_ceo_what_kind_of_failure_it_is(client, factory):
    manager, project_id, task_id = failed_mission(
        factory, [False, False, False], second=Scripted([]), max_task_retries=2
    )

    failed = task_of(client, project_id, "product_validation")
    assert failed["recovery"] == {
        "kind": "reassign_required",
        "can_retry": False,
        "attempts_current_assignment": 3,
        "max_attempts_per_assignment": 3,
        "attempts_total": 3,
        "max_attempts_per_task": 6,
        "next_attempt": 4,
    }
    assert task_of(client, project_id, "supplier_sourcing")["recovery"]["kind"] == "blocked"
    assert task_of(client, project_id, "decision_synthesis")["recovery"]["kind"] == "blocked"
    manager._registry._agents.pop(P1)
    assert task_of(client, project_id, "product_validation")["recovery"]["kind"] == "unknown_agent"


def test_recovery_of_a_healthy_mission_is_none_everywhere(client, factory):
    _, project_id, _ = failed_mission(factory, [])
    for task in client.get("/api/tasks", params={"project_id": project_id}).json():
        assert task["recovery"]["kind"] == "none"
        assert task["recovery"]["can_retry"] is False


def test_the_assigned_agent_must_be_available_to_retry(client, factory):
    manager, _, task_id = failed_mission(factory, [False, False, True])
    manager._registry.set_status(P1, AgentStatus.DISABLED)

    response = client.post(f"/api/tasks/{task_id}/retry", json={"after_attempt": 2})

    assert response.status_code == 409
    assert "not available" in response.json()["detail"]


def test_only_owner_and_admin_may_recover_tasks():
    assert ApiAction.TASK_RECOVER == "task.recover"
    allowed = {role for role in RoleName if role_can(role, ApiAction.TASK_RECOVER)}
    assert allowed == {RoleName.OWNER, RoleName.ADMIN}


def test_both_routes_demand_an_identity_when_auth_is_required():
    from app.core.config import Settings, get_settings

    def required() -> Settings:
        return Settings(_env_file=None, require_auth=True, supabase_url="https://example.supabase.co")

    app.dependency_overrides[get_settings] = required
    try:
        client = TestClient(app)
        assert client.post("/api/tasks/x/retry", json={"after_attempt": 1}).status_code == 401
        assert client.post("/api/tasks/x/reassign", json={"agent_id": P1, "reason": "abc"}).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)
