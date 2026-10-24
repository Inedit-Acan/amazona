"""`POST /api/test-support/faults`: armar un fallo de ENSAYO (M51A).

Una sola ruta, fuera del esquema público, que solo existe si la funcionalidad está activada Y el entorno lo permite
(`development` + todos los proveedores simulados). Apagada responde 404 a TODO el mundo, antes de
mirar quién pregunta. Armar exige
una identidad VERIFICADA con rol OWNER o ADMIN (también en development, donde el resto de rutas no
hace cumplir los roles) e
`Idempotency-Key`, y se audita (`fault.armed`). No hay ninguna otra operación: no se desarma, no se
lista, no se arma en bloque."""

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.tasks import get_agent_manager
from app.auth.actor import RoleName
from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.core.config import Environment, ProviderKind, Settings, get_settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.role import Role
from app.db.models.task import Task
from app.db.models.user import User
from app.db.session import get_db
from app.fault_injection import FaultInjector, get_fault_injector, set_fault_injector
from app.main import app
from app.permissions.policies import ApiAction, role_can

URL = "/api/test-support/faults"
SUPABASE_URL = "https://example.supabase.co"
USERS: dict[RoleName, str] = {role: f"sub-{role.value.lower()}" for role in RoleName}
CONTEXT = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
}


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as seed:  # lo que siembra la migración de M29, y un usuario por rol
        for role in RoleName:
            seed.add(Role(id=f"role-{role.value.lower()}", name=role.value))
        seed.flush()
        for role, subject in USERS.items():
            seed.add(
                User(email=f"{role.value.lower()}@amazona.local", role_id=f"role-{role.value.lower()}", subject=subject)
            )
        seed.commit()

    def override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    previous = get_fault_injector()
    set_fault_injector(FaultInjector())
    try:
        yield session_factory
    finally:
        set_fault_injector(previous)
        for dependency in (get_db, get_settings, get_agent_manager, get_auth_service):
            app.dependency_overrides.pop(dependency, None)
        engine.dispose()


def token_for(private_key, role: RoleName) -> str:
    now = datetime.datetime.now(datetime.UTC)
    return jwt.encode(
        {
            "sub": USERS[role],
            "email": f"{role.value.lower()}@amazona.local",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "exp": now + datetime.timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )


def use_settings(public_key, **over) -> None:
    """Los ajustes de la petición (con identidad exigida) y el verificador de tokens de la prueba."""
    args = {
        "fault_injection_enabled": True,
        "require_auth": True,
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": "anon-key",
    }
    args.update(over)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, **args)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        supabase_url=SUPABASE_URL, audience="authenticated", get_signing_key=lambda token: public_key
    )


@pytest.fixture()
def client(factory) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def enabled(monkeypatch, key_pair, factory, client):
    """Activada en un desarrollo con todos los proveedores simulados y con identidad exigida; el
    cliente va como OWNER."""
    private_key, public_key = key_pair
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")  # también para el código que lee los ajustes directamente
    get_settings.cache_clear()
    use_settings(public_key)
    client.headers.update({"Authorization": f"Bearer {token_for(private_key, RoleName.OWNER)}"})
    yield
    get_settings.cache_clear()


def make_objective(factory) -> str:
    with factory() as db:
        row = Objective(title="[ENSAYO] resiliencia", created_by="owner", context=CONTEXT)
        db.add(row)
        db.commit()
        return row.id


def arm(client, objective_id, key="arm-fault-0001", headers=None, **over):
    body = {"objective_id": objective_id, "task_name": "product_validation", "attempt": 1}
    body.update(over)
    sent = dict(headers or {})
    if key:
        sent["Idempotency-Key"] = key
    return client.post(URL, json=body, headers=sent)


def audit(factory, action):
    with factory() as db:
        return db.query(AuditLog).filter_by(action=action).all()


# A. apagada: 404


def test_A_off_by_default_the_route_answers_404_and_writes_nothing(client, factory):
    objective_id = make_objective(factory)

    response = arm(client, objective_id)

    assert response.status_code == 404
    assert get_fault_injector().armed() == []
    assert audit(factory, "fault.armed") == []


def test_A_off_the_route_is_not_in_the_public_schema():
    assert URL not in app.openapi()["paths"]


def test_A_off_it_is_404_even_for_a_verified_owner(client, factory, key_pair):
    private_key, public_key = key_pair
    use_settings(public_key, fault_injection_enabled=False)
    objective_id = make_objective(factory)

    response = arm(client, objective_id, headers={"Authorization": f"Bearer {token_for(private_key, RoleName.OWNER)}"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": Environment.PRODUCTION},
        {"environment": Environment.STAGING},
        {"environment": Environment.DEMO},
        {"payments_provider": ProviderKind.SANDBOX},
        {"suppliers_provider": ProviderKind.REAL},
    ],
)
def test_enabled_but_in_an_environment_that_does_not_allow_it_the_route_is_404_before_asking_who_you_are(
    client, factory, key_pair, overrides
):
    private_key, public_key = key_pair
    use_settings(public_key, **overrides)
    objective_id = make_objective(factory)

    anonymous = arm(client, objective_id)
    owner = arm(client, objective_id, headers={"Authorization": f"Bearer {token_for(private_key, RoleName.OWNER)}"})

    assert anonymous.status_code == owner.status_code == 404
    assert get_fault_injector().armed() == []


# B / P. activada en development + mocks: se puede armar, y se audita


def test_B_P_enabled_in_development_with_mocks_it_arms_and_audits(client, factory, enabled):
    objective_id = make_objective(factory)

    response = arm(client, objective_id)

    assert response.status_code == 200
    body = response.json()
    assert (body["objective_id"], body["task_name"], body["attempt"]) == (objective_id, "product_validation", 1)
    expires = datetime.datetime.fromisoformat(body["expires_at"])
    remaining = expires - datetime.datetime.now(datetime.UTC)
    assert datetime.timedelta(minutes=29) < remaining <= datetime.timedelta(minutes=30)
    assert [(f.objective_id, f.task_name, f.attempt) for f in get_fault_injector().armed()] == [
        (objective_id, "product_validation", 1)
    ]
    rows = audit(factory, "fault.armed")
    assert len(rows) == 1
    after = rows[0].after
    assert (after["objective_id"], after["task"], after["attempt"]) == (objective_id, "product_validation", 1)
    assert after["actor"] == "sub-owner" and after["expires_at"] == body["expires_at"]
    assert rows[0].correlation_id == body["correlation_id"]
    assert not any(secret in str(after).lower() for secret in ("token", "password", "secret", "key"))


def test_the_idempotency_key_is_mandatory_even_in_a_simulation(client, factory, enabled):
    objective_id = make_objective(factory)

    response = arm(client, objective_id, key=None)

    assert response.status_code == 428
    assert get_fault_injector().armed() == []


def test_the_same_key_replays_without_arming_twice(client, factory, enabled):
    objective_id = make_objective(factory)

    first = arm(client, objective_id, key="same-key-0001")
    second = arm(client, objective_id, key="same-key-0001")

    assert first.status_code == second.status_code == 200
    assert second.headers.get("Idempotency-Replayed") == "true" and second.json() == first.json()
    assert len(get_fault_injector().armed()) == 1
    assert len(audit(factory, "fault.armed")) == 1


def test_a_second_fault_cannot_be_armed_while_one_is_pending(client, factory, enabled):
    objective_id = make_objective(factory)
    arm(client, objective_id, key="k-one-0001")

    response = arm(client, objective_id, key="k-two-0001", task_name="legal_validation")

    assert response.status_code == 409
    assert len(get_fault_injector().armed()) == 1


# F / G / H. lo que no se puede armar


@pytest.mark.parametrize(
    "task_name", ["finance_validation", "decision_synthesis", "no_such_task", "product_*", "*", "Product_Validation"]
)
def test_F_G_H_a_task_outside_the_closed_list_is_422_and_nothing_is_armed_or_audited(
    client, factory, enabled, task_name
):
    objective_id = make_objective(factory)

    response = arm(client, objective_id, task_name=task_name)

    assert response.status_code == 422
    assert get_fault_injector().armed() == []
    assert audit(factory, "fault.armed") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"attempt": 0},
        {"attempt": 4},
        {"attempt": "1"},
        {"objective_id": ""},
        {"objective_id": "*"},
        {"objective_id": "obj%"},
        {"extra": "x"},
        {"task_name": None},
    ],
)
def test_a_malformed_or_wildcard_body_is_422(client, factory, enabled, payload):
    objective_id = make_objective(factory)
    body = {"objective_id": objective_id, "task_name": "product_validation", "attempt": 1, **payload}

    response = client.post(URL, json=body, headers={"Idempotency-Key": "bad-body-0001"})

    assert response.status_code == 422
    assert get_fault_injector().armed() == []


def test_an_objective_that_does_not_exist_is_404(client, factory, enabled):
    response = arm(client, "00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert get_fault_injector().armed() == []


# autoridad: solo una identidad VERIFICADA con rol OWNER o ADMIN, también en development


def test_only_owner_and_admin_may_arm_by_policy():
    assert ApiAction.FAULT_INJECT == "fault.inject"
    assert {role for role in RoleName if role_can(role, ApiAction.FAULT_INJECT)} == {RoleName.OWNER, RoleName.ADMIN}


@pytest.mark.parametrize("role", list(RoleName))
def test_over_http_only_owner_and_admin_can_arm_even_in_development(client, factory, enabled, key_pair, role):
    private_key, _ = key_pair
    objective_id = make_objective(factory)

    response = arm(
        client,
        objective_id,
        key=f"role-{role.value.lower()}-0001",
        headers={"Authorization": f"Bearer {token_for(private_key, role)}"},
    )

    expected = 200 if role in (RoleName.OWNER, RoleName.ADMIN) else 403
    assert response.status_code == expected, role
    assert len(get_fault_injector().armed()) == (1 if expected == 200 else 0)


def test_without_a_token_it_is_401_when_auth_is_required(client, factory, enabled):
    objective_id = make_objective(factory)
    client.headers.pop("Authorization")

    response = arm(client, objective_id)

    assert response.status_code == 401
    assert get_fault_injector().armed() == []


def test_the_local_unauthenticated_operator_cannot_arm_even_with_the_feature_on(client, factory, key_pair):
    _, public_key = key_pair
    use_settings(public_key, require_auth=False)  # desarrollo local sin identidad
    objective_id = make_objective(factory)

    response = arm(client, objective_id)

    assert response.status_code == 401
    assert get_fault_injector().armed() == []


def _all_routes(router) -> list[APIRoute]:
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            nested = getattr(route, "original_router", None) or (route if hasattr(route, "routes") else None)
            if nested is not None:
                found.extend(_all_routes(nested))
    return found


def test_the_only_new_http_surface_is_one_post():
    routes = [route for route in _all_routes(app) if route.path.startswith("/api/test-support")]
    assert [(route.path, sorted(route.methods)) for route in routes] == [(URL, ["POST"])]
    assert routes[0].include_in_schema is False


# extremo a extremo por HTTP: armar → /run → FAILED con un intento → retry → ready_to_resume → resume → nueva decisión


def test_end_to_end_through_the_api_with_the_default_agents(client, factory, enabled):
    objective_id = make_objective(factory)
    assert arm(client, objective_id).status_code == 200

    run = client.post(f"/api/objectives/{objective_id}/run", headers={"Idempotency-Key": "run-e2e-0001"})
    assert run.status_code == 200 and run.json()["status"] == "REVIEW"
    v1 = run.json()
    project_id = v1["project_id"]
    assert v1["rationale"].startswith("incomplete_mission")

    tasks = {t["name"]: t for t in client.get("/api/tasks", params={"project_id": project_id}).json()}
    product = tasks["product_validation"]
    assert product["status"] == "FAILED" and product["assigned_agent_id"] == "agent-product-1"
    assert [(e["attempt"], e["success"]) for e in product["agent_relation"]["executions"]] == [(1, False)]
    assert product["recovery"]["kind"] == "recoverable"
    assert client.get(f"/api/projects/{project_id}/mission").json()["state"] == "recovery_pending"
    assert get_fault_injector().armed() == []

    retry = client.post(
        f"/api/tasks/{product['id']}/retry", json={"after_attempt": 1}, headers={"Idempotency-Key": "retry-e2e-0001"}
    )
    assert retry.status_code == 200 and retry.json()["status"] == "COMPLETED"
    assert retry.json()["assigned_agent_id"] == "agent-product-1"
    executions = retry.json()["agent_relation"]["executions"]
    assert [(e["attempt"], e["success"]) for e in executions] == [(1, False), (2, True)]
    assert client.get(f"/api/projects/{project_id}/mission").json()["state"] == "ready_to_resume"

    resume = client.post(
        f"/api/objectives/{objective_id}/resume",
        json={"after_decision_id": v1["id"], "project_id": project_id},
        headers={"Idempotency-Key": "resume-e2e-0001"},
    )
    assert resume.status_code == 200
    v2 = resume.json()
    assert v2["id"] != v1["id"] and v2["status"] != "REVIEW" and v2["state"] == "complete"
    assert v2["correlation_id"] == v1["correlation_id"]
    with factory() as db:
        assert db.query(Task).filter_by(project_id=project_id).count() == 5
        assert db.query(Decision).filter_by(project_id=project_id).count() == 2
    assert len(audit(factory, "fault.armed")) == len(audit(factory, "fault.fired")) == 1
