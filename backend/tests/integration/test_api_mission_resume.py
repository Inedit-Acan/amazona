"""`POST /api/objectives/{id}/resume`, `GET /api/projects/{id}/mission` y la versión de las decisiones (M50, Commit 9).

Una ruta nueva de efecto (reanudar ejecuta agentes y escribe una decisión), con contrato estricto: el cuerpo nombra
la decisión que el cliente VIO (`after_decision_id`), como el reintento nombra el intento. Repetir con la misma
`Idempotency-Key` devuelve lo mismo sin volver a ejecutar; sin clave, la repetición es un 409 por obsoleta."""

import pytest
from fastapi.testclient import TestClient
from mission_test_support import P1, counts, incomplete_mission, recovered_mission
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.tasks import get_agent_manager
from app.auth.actor import RoleName
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.models.decision import Decision
from app.db.models.project import Project
from app.db.session import get_db
from app.main import app
from app.permissions.policies import ApiAction, role_can


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
        for dependency in (get_db, get_agent_manager, get_settings):
            app.dependency_overrides.pop(dependency, None)
        engine.dispose()


@pytest.fixture()
def client(factory) -> TestClient:
    return TestClient(app)


def recovered(factory, **kwargs):
    with factory() as db:
        mission = recovered_mission(db, **kwargs)
        app.dependency_overrides[get_agent_manager] = lambda: mission.manager
        return mission.objective.id, mission.project.id, mission.latest().id, mission.manager


def resume_body(decision_id: str, **extra) -> dict:
    return {"after_decision_id": decision_id, **extra}


def test_the_new_routes_exist_with_the_right_methods():
    paths = app.openapi()["paths"]
    assert set(paths["/api/objectives/{objective_id}/resume"]) == {"post"}
    assert set(paths["/api/projects/{project_id}/mission"]) == {"get"}


def test_resume_continues_the_mission_and_answers_with_the_new_decision(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)

    response = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id))

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["objective_id"] == objective_id
    assert body["previous_decision_id"] == old_id
    assert body["id"] != old_id
    assert body["status"] != "REVIEW"
    assert body["state"] == "complete"
    assert body["executed_tasks"] == [
        "supplier_sourcing",
        "legal_validation",
        "finance_validation",
        "decision_synthesis",
    ]
    with factory() as db:
        assert db.query(Decision).filter_by(project_id=project_id).count() == 2


def test_the_decision_listing_says_which_decision_is_current_and_keeps_the_old_one(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)
    new_id = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id)).json()["id"]

    listing = client.get("/api/decisions", params={"project_id": project_id}).json()

    assert [(d["id"], d["version"], d["is_current"], d["supersedes_decision_id"]) for d in listing] == [
        (old_id, 1, False, None),
        (new_id, 2, True, old_id),
    ]
    assert listing[0]["status"] == "REVIEW"
    one = client.get(f"/api/decisions/{old_id}").json()
    assert (one["version"], one["is_current"]) == (1, False)


def test_a_single_decision_is_version_one_and_current(client, factory):
    with factory() as db:
        mission = incomplete_mission(db, script=(True,))
        project_id = mission.project.id

    listing = client.get("/api/decisions", params={"project_id": project_id}).json()

    assert [(d["version"], d["is_current"], d["supersedes_decision_id"]) for d in listing] == [(1, True, None)]


def test_L_the_same_idempotency_key_replays_without_executing_again(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)
    headers = {"Idempotency-Key": "resume-mission-0001"}

    first = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id), headers=headers)
    with factory() as db:
        after_first = counts(db)
    second = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id), headers=headers)

    assert first.status_code == second.status_code == 200
    assert second.headers.get("Idempotency-Replayed") == "true"
    assert second.json() == first.json()
    with factory() as db:
        assert counts(db) == after_first


def test_the_same_key_with_another_body_is_a_conflict(client, factory):
    objective_id, _, old_id, _ = recovered(factory)
    headers = {"Idempotency-Key": "resume-mission-0002"}
    client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id), headers=headers)

    other = client.post(
        f"/api/objectives/{objective_id}/resume", json=resume_body(old_id, reason="different"), headers=headers
    )

    assert other.status_code == 409


def test_repeating_without_a_key_is_refused_as_stale_and_runs_nothing(client, factory):
    objective_id, _, old_id, _ = recovered(factory)
    client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id))
    with factory() as db:
        before = counts(db)

    again = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id))

    assert again.status_code == 409
    with factory() as db:
        assert counts(db) == before


def test_G_resuming_a_complete_mission_is_a_409(client, factory):
    objective_id, _, old_id, _ = recovered(factory)
    new_id = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id)).json()["id"]

    response = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(new_id))

    assert response.status_code == 409
    assert "complete" in response.json()["detail"]


def test_H_a_failed_task_unresolved_is_a_409_that_names_it(client, factory):
    with factory() as db:
        mission = incomplete_mission(db)
        app.dependency_overrides[get_agent_manager] = lambda: mission.manager
        objective_id, decision_id = mission.objective.id, mission.latest().id

    response = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(decision_id))

    assert response.status_code == 409
    assert "product_validation" in response.json()["detail"]


def test_an_unknown_objective_is_404_and_a_project_of_another_objective_is_404(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)

    assert client.post("/api/objectives/nope/resume", json=resume_body(old_id)).status_code == 404
    with factory() as db:
        other = incomplete_mission(db, script=(True,))
    foreign = client.post(
        f"/api/objectives/{objective_id}/resume", json=resume_body(old_id, project_id=other.project.id)
    )
    assert foreign.status_code == 404


def test_an_objective_with_two_projects_needs_the_project_to_be_named(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)
    with factory() as db:
        db.add(Project(objective_id=objective_id, name="second run", status="VALIDATING"))
        db.commit()

    ambiguous = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id))
    named = client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id, project_id=project_id))

    assert ambiguous.status_code == 409
    assert "project_id" in ambiguous.json()["detail"]
    assert named.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [{}, {"after_decision_id": ""}, {"after_decision_id": "x" * 37}, {"after_decision_id": "a", "extra": 1}],
)
def test_a_malformed_body_is_422(client, factory, payload):
    objective_id, *_ = recovered(factory)

    assert client.post(f"/api/objectives/{objective_id}/resume", json=payload).status_code == 422


def test_the_mission_endpoint_describes_an_incomplete_failed_mission(client, factory):
    with factory() as db:
        mission = incomplete_mission(db)
        app.dependency_overrides[get_agent_manager] = lambda: mission.manager
        project_id = mission.project.id

    body = client.get(f"/api/projects/{project_id}/mission").json()

    assert body["state"] == "recovery_pending"
    assert body["resumable"] is False
    assert body["resumed"] is False
    assert body["blockers"] == [{"task": "product_validation", "reason": "failed_recoverable"}]
    assert body["pending_tasks"][0] == "product_validation"
    assert body["decisions"] == 1


def test_the_mission_endpoint_goes_from_ready_to_resumed(client, factory):
    objective_id, project_id, old_id, _ = recovered(factory)

    ready = client.get(f"/api/projects/{project_id}/mission").json()
    client.post(f"/api/objectives/{objective_id}/resume", json=resume_body(old_id))
    done = client.get(f"/api/projects/{project_id}/mission").json()

    assert (ready["state"], ready["resumable"], ready["resumed"]) == ("ready_to_resume", True, False)
    assert ready["blockers"] == []
    assert (done["state"], done["resumable"], done["resumed"]) == ("complete", False, True)
    assert done["decisions"] == 2


def test_the_mission_endpoint_of_an_unknown_project_is_404(client, factory):
    assert client.get("/api/projects/nope/mission").status_code == 404


def test_only_owner_and_admin_may_resume_a_mission():
    allowed = {role for role in RoleName if role_can(role, ApiAction.TASK_RECOVER)}
    assert allowed == {RoleName.OWNER, RoleName.ADMIN}


def test_the_route_demands_an_identity_when_auth_is_required():
    def required() -> Settings:
        return Settings(_env_file=None, require_auth=True, supabase_url="https://example.supabase.co")

    app.dependency_overrides[get_settings] = required
    try:
        assert TestClient(app).post("/api/objectives/x/resume", json={"after_decision_id": P1}).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)
