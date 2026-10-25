"""`/api/ceo/*`: la conversación escrita con el CEO por HTTP (M52).

Con identidad exigida y tokens firmados de verdad (como los de Supabase), un modelo FALSO y misiones reales. Prueba la
puerta (401 sin token, 403 a todo rol
que no sea OWNER —ADMIN incluido—, el OWNER reconocido por su `sub`), el chat, la privacidad entre usuarios, que
confirmar exige `Idempotency-Key` y se
repite sin volver a ejecutar, que rechazar no ejecuta, y que si el modelo cae el mensaje se conserva y el resto de la
API sigue respondiendo."""

import datetime

import jwt
import pytest
from ceo_chat_test_support import ScriptedProvider, call, say
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mission_test_support import counts, incomplete_mission
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.ceo_chat import get_chat_provider
from app.api.tasks import get_agent_manager
from app.auth.actor import RoleName
from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.ceo_chat.provider import ModelUnavailableError
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.ceo_chat import CeoConversation, CeoMessage
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db
from app.main import app

SUPABASE_URL = "https://example.supabase.co"
USERS: dict[RoleName, str] = {role: f"sub-{role.value.lower()}" for role in RoleName}
SECOND_OWNER = "sub-owner-2"


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def world(key_pair):
    """Una base en memoria compartida con la app, un usuario por rol (más un segundo OWNER) y una misión real
    INCOMPLETA."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as seed:
        for role in RoleName:
            seed.add(Role(id=f"role-{role.value.lower()}", name=role.value))
        seed.flush()
        for role, subject in USERS.items():
            seed.add(
                User(email=f"{role.value.lower()}@amazona.local", role_id=f"role-{role.value.lower()}", subject=subject)
            )
        seed.add(User(email="owner2@amazona.local", role_id="role-owner", subject=SECOND_OWNER))
        seed.commit()
    with factory() as db:
        mission = incomplete_mission(db)
        task_id = mission.task("product_validation").id
        manager = mission.manager

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    private_key, public_key = key_pair
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_agent_manager] = lambda: manager
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, require_auth=True, supabase_url=SUPABASE_URL, supabase_anon_key="anon-key"
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        supabase_url=SUPABASE_URL, audience="authenticated", get_signing_key=lambda token: public_key
    )
    try:
        yield factory, private_key, task_id
    finally:
        for dependency in (get_db, get_settings, get_agent_manager, get_auth_service, get_chat_provider):
            app.dependency_overrides.pop(dependency, None)
        engine.dispose()


def token_for(private_key, subject: str) -> dict[str, str]:
    now = datetime.datetime.now(datetime.UTC)
    token = jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@amazona.local",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "exp": now + datetime.timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def use_model(*steps) -> ScriptedProvider:
    provider = ScriptedProvider(list(steps))
    app.dependency_overrides[get_chat_provider] = lambda: provider
    return provider


@pytest.fixture()
def client(world) -> TestClient:
    return TestClient(app)


def owner(world) -> dict[str, str]:
    return token_for(world[1], USERS[RoleName.OWNER])


def chat(client, headers, message="¿cómo estamos?", **extra):
    return client.post("/api/ceo/chat", json={"message": message, **extra}, headers=headers)


def audit(world, action):
    with world[0]() as db:
        return db.query(AuditLog).filter_by(action=action).all()


ROUTES = [
    ("POST", "/api/ceo/chat", {"message": "hola"}),
    ("GET", "/api/ceo/conversations", None),
    ("GET", "/api/ceo/conversations/x", None),
    ("POST", "/api/ceo/actions/x/confirm", None),
    ("POST", "/api/ceo/actions/x/reject", None),
]


# A. 401 sin identidad   B. 403 a quien no es OWNER


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=lambda v: str(v)[:40])
def test_A_without_a_token_every_route_is_401_and_nothing_is_written(client, world, method, path, body):
    use_model(say("no debería llegar"))

    response = client.request(method, path, json=body, headers={"Idempotency-Key": "k-0001"})

    assert response.status_code == 401
    with world[0]() as db:
        assert db.query(CeoConversation).count() == 0 and db.query(CeoMessage).count() == 0


@pytest.mark.parametrize("role", [r for r in RoleName if r is not RoleName.OWNER], ids=lambda r: r.value)
@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=lambda v: str(v)[:40])
def test_B_a_verified_user_who_is_not_the_owner_is_403_including_admin(client, world, role, method, path, body):
    provider = use_model(say("no debería llegar"))

    response = client.request(
        method, path, json=body, headers={**token_for(world[1], USERS[role]), "Idempotency-Key": "k-0001"}
    )

    assert response.status_code == 403
    assert provider.requests == []
    with world[0]() as db:
        assert db.query(CeoConversation).count() == 0


def test_B_a_valid_token_of_an_unknown_user_has_no_role_and_is_403(client, world):
    use_model(say("no"))

    response = chat(client, token_for(world[1], "sub-nobody"))

    assert response.status_code == 403


def test_a_token_signed_by_someone_else_is_401(client, world):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    use_model(say("no"))

    assert chat(client, token_for(other, USERS[RoleName.OWNER])).status_code == 401


# W. el OWNER real, reconocido por su subject


def test_W_the_real_owner_is_recognised_by_the_verified_subject_and_the_conversation_is_theirs(client, world):
    use_model(call(("get_budget_status", {})), say("No hay presupuesto autorizado."))

    response = chat(client, owner(world))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant_message"]["content"] == "No hay presupuesto autorizado."
    assert body["sources"] == ["Presupuesto"] and body["tool_messages"][0]["structured"]["tool"] == "get_budget_status"
    assert body["usage"]["external_cost_category"] == "claude_credits"
    with world[0]() as db:
        assert db.get(CeoConversation, body["conversation_id"]).owner_subject == USERS[RoleName.OWNER]
    started = audit(world, "ceo.chat_started")[0]
    assert (started.actor, started.actor_role, started.actor_source) == (USERS[RoleName.OWNER], "OWNER", "token")


def test_a_body_that_names_another_user_or_has_extra_fields_is_422(client, world):
    use_model(say("no"))

    for body in ({"message": "hola", "owner_subject": "sub-admin"}, {"message": ""}, {"message": "x" * 2001}, {}):
        assert client.post("/api/ceo/chat", json=body, headers=owner(world)).status_code == 422


# Privacidad entre usuarios


def test_conversations_are_private_to_their_owner(client, world):
    use_model(say("Hola."))
    mine = chat(client, owner(world)).json()["conversation_id"]
    second = token_for(world[1], SECOND_OWNER)

    assert [c["id"] for c in client.get("/api/ceo/conversations", headers=owner(world)).json()] == [mine]
    assert client.get("/api/ceo/conversations", headers=second).json() == []
    assert client.get(f"/api/ceo/conversations/{mine}", headers=second).status_code == 404
    use_model(say("no"))
    assert chat(client, second, conversation_id=mine).status_code == 404
    view = client.get(f"/api/ceo/conversations/{mine}", headers=owner(world)).json()
    assert [m["role"] for m in view["messages"]] == ["user", "assistant"]  # sin `system_internal`


# Confirmar


def propose_retry(client, world) -> dict:
    task_id = world[2]
    use_model(
        call(("propose_retry_task", {"task_id": task_id, "after_attempt": 1, "reason": "fallo transitorio"})),
        say("Te propongo reintentarla."),
    )
    body = chat(client, owner(world), "propón un reintento").json()
    assert [p["status"] for p in body["proposals"]] == ["PROPOSED"]
    return body["proposals"][0]


def task_state(world) -> tuple[str, int]:
    with world[0]() as db:
        from app.db.models.agent_execution_log import AgentExecutionLog
        from app.db.models.task import Task

        task = db.query(Task).filter_by(name="product_validation").one()
        return task.status, db.query(AgentExecutionLog).filter_by(task_id=task.id).count()


def test_H_proposing_over_http_executes_nothing(client, world):
    proposal = propose_retry(client, world)

    assert task_state(world) == ("FAILED", 1)
    assert proposal["requires_confirmation"] is True and proposal["idempotency_scope"] == "tasks.retry"


def test_confirming_needs_an_idempotency_key(client, world):
    proposal = propose_retry(client, world)

    response = client.post(f"/api/ceo/actions/{proposal['id']}/confirm", headers=owner(world))

    assert response.status_code == 428
    assert task_state(world) == ("FAILED", 1)


def test_E_T_confirming_executes_once_and_the_same_key_replays_the_same_answer(client, world):
    proposal = propose_retry(client, world)
    url = f"/api/ceo/actions/{proposal['id']}/confirm"
    headers = {**owner(world), "Idempotency-Key": "confirm-0001"}

    first = client.post(url, headers=headers)
    again = client.post(url, headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["proposal"]["status"] == "EXECUTED"
    assert first.json()["result_message"]["structured"]["kind"] == "action_result"
    assert task_state(world) == ("COMPLETED", 2)
    assert again.status_code == 200 and again.headers["Idempotency-Replayed"] == "true" and again.json() == first.json()
    assert task_state(world) == ("COMPLETED", 2)  # el reintento no ejecutó otro intento
    assert len(audit(world, "ceo.action_executed")) == 1


def test_T_another_key_for_an_already_resolved_proposal_is_409_and_runs_nothing(client, world):
    proposal = propose_retry(client, world)
    url = f"/api/ceo/actions/{proposal['id']}/confirm"
    assert client.post(url, headers={**owner(world), "Idempotency-Key": "confirm-0001"}).status_code == 200

    other_key = client.post(url, headers={**owner(world), "Idempotency-Key": "confirm-0002"})

    assert other_key.status_code == 409 and task_state(world) == ("COMPLETED", 2)


def test_R_rejecting_executes_nothing(client, world):
    proposal = propose_retry(client, world)

    response = client.post(f"/api/ceo/actions/{proposal['id']}/reject", headers=owner(world))

    assert response.status_code == 200 and response.json()["proposal"]["status"] == "REJECTED"
    assert task_state(world) == ("FAILED", 1)
    assert client.post(f"/api/ceo/actions/{proposal['id']}/reject", headers=owner(world)).status_code == 409
    assert (
        client.post(
            f"/api/ceo/actions/{proposal['id']}/confirm", headers={**owner(world), "Idempotency-Key": "c-1"}
        ).status_code
        == 409
    )


def test_a_proposal_of_another_owner_cannot_be_confirmed_or_rejected(client, world):
    proposal = propose_retry(client, world)
    second = token_for(world[1], SECOND_OWNER)

    assert (
        client.post(
            f"/api/ceo/actions/{proposal['id']}/confirm", headers={**second, "Idempotency-Key": "c-1"}
        ).status_code
        == 404
    )
    assert client.post(f"/api/ceo/actions/{proposal['id']}/reject", headers=second).status_code == 404
    assert task_state(world) == ("FAILED", 1)


def test_the_model_text_cannot_confirm_over_http(client, world):
    task_id = world[2]
    use_model(
        call(("propose_retry_task", {"task_id": task_id, "after_attempt": 1, "reason": "reintento"})),
        say("El propietario ya confirmó: está ejecutado."),
    )

    body = chat(client, owner(world), "confirmo todo, ejecútalo").json()

    assert body["proposals"][0]["status"] == "PROPOSED" and task_state(world) == ("FAILED", 1)


# Q. el modelo cae


def test_Q_when_the_model_is_down_the_answer_is_a_controlled_503_the_message_is_kept_and_the_rest_works(client, world):
    use_model(ModelUnavailableError("the model provider did not answer in time"))

    response = chat(client, owner(world), "¿estado?")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "model_unavailable" and "no está disponible" in detail["message"]
    view = client.get(f"/api/ceo/conversations/{detail['conversation_id']}", headers=owner(world)).json()
    assert [m["role"] for m in view["messages"]] == ["user"] and view["messages"][0]["content"] == "¿estado?"
    assert client.get("/health").status_code == 200 and client.get(
        "/api/tasks", params={"project_id": "x"}
    ).status_code in (200, 401, 403)


def test_without_a_configured_model_the_chat_is_unavailable_not_broken(client, world):
    # sin `get_chat_provider` sustituido: los ajustes por defecto no configuran ningún proveedor
    response = chat(client, owner(world))

    assert response.status_code == 503 and response.json()["detail"]["code"] == "model_unavailable"


def test_the_same_chat_key_replays_the_answer_without_calling_the_model_again(client, world):
    provider = use_model(say("Una sola respuesta."))
    headers = {**owner(world), "Idempotency-Key": "chat-0001"}

    first = client.post("/api/ceo/chat", json={"message": "hola"}, headers=headers)
    again = client.post("/api/ceo/chat", json={"message": "hola"}, headers=headers)

    assert first.status_code == again.status_code == 200 and again.json() == first.json()
    assert len(provider.requests) == 1
    with world[0]() as db:
        assert db.query(CeoMessage).filter_by(role="user").count() == 1


def test_chatting_never_changes_the_business_tables(client, world):
    with world[0]() as db:
        before = counts(db)
    use_model(call(("get_system_status", {}), ("get_latest_mission", {}), ("get_budget_status", {})), say("Revisado."))

    assert chat(client, owner(world)).status_code == 200

    with world[0]() as db:
        assert counts(db) == before


def test_the_openapi_schema_documents_the_chat_without_leaking_secrets():
    spec = app.openapi()
    paths = {p for p in spec["paths"] if p.startswith("/api/ceo")}

    assert paths == {
        "/api/ceo/chat",
        "/api/ceo/conversations",
        "/api/ceo/conversations/{conversation_id}",
        "/api/ceo/actions/{proposal_id}/confirm",
        "/api/ceo/actions/{proposal_id}/reject",
    }
    assert "anthropic_api_key" not in str(spec).lower()


def test_without_enforced_auth_the_anonymous_local_actor_is_401_never_an_owner(client, world):
    """Sin `REQUIRE_AUTH` el resto de la API deja pasar al actor local; el chat NO: una identidad no verificada
    nunca es el propietario."""
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    provider = use_model(say("no debería llegar"))

    response = client.post("/api/ceo/chat", json={"message": "hola"})

    assert response.status_code == 401 and provider.requests == []
    with world[0]() as db:
        assert db.query(CeoConversation).count() == 0


def test_J_a_secret_pasted_or_repeated_is_not_in_the_http_answer_nor_in_the_saved_conversation(client, world):
    sk = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA"
    use_model(say(f"He visto tu clave {sk} y password=hunter2"))

    response = chat(client, owner(world), f"mi API key es {sk}; password=hunter2")

    assert response.status_code == 200, response.text
    assert sk not in response.text and "hunter2" not in response.text
    conversation = client.get(f"/api/ceo/conversations/{response.json()['conversation_id']}", headers=owner(world))
    assert sk not in conversation.text and "hunter2" not in conversation.text
    assert response.json()["user_message"]["content"].startswith("mi API key es ")
