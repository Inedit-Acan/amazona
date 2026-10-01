"""Idempotencia genérica de las rutas síncronas con efecto (hardening pre-M44, ADR 0025).

Qué se promete, y qué no:

- misma clave y mismo contenido → la misma respuesta, sin ejecutar nada otra vez;
- misma clave y otro contenido → 409 (es otra petición escondida tras la misma clave);
- claves distintas, operaciones distintas o personas distintas no chocan;
- una negativa del dominio (no hizo nada) libera la clave; un fallo que no dice si hubo efecto la bloquea;
- ninguna caducidad deja volver a ejecutar una petición que quizá ya se ejecutó.

Las rutas se usan de verdad (TestClient); el contenido de cada efecto es el de siempre.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from app.api.research import ResearchRunCreate
from app.auth.actor import Actor, ActorSource, RoleName
from app.auth.dependencies import LOCAL_SUBJECT
from app.core.config import Settings, get_settings
from app.core.errors import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyOutcomeUnknownError,
    NotFoundError,
    ValidationError,
)
from app.db.base import Base
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.product_analysis import ProductAnalysis
from app.db.session import get_db
from app.idempotency.service import (
    COMPLETED,
    IN_PROGRESS,
    UNKNOWN_OUTCOME,
    IdempotencyService,
    Replay,
    actor_scope,
    request_hash,
    run_idempotent,
    validated_key,
)
from app.integrations.ports import ProviderKind
from app.main import app
from app.research.service import ResearchService

LOCAL_ACTOR = Actor(subject=LOCAL_SUBJECT, email=None, role=None, source=ActorSource.DECLARED)
OWNER = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
OTHER = Actor(subject="other@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)
REAL = Settings(_env_file=None, ads_provider=ProviderKind.REAL)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


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
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)


def records(session_factory) -> list[IdempotencyRecord]:
    with session_factory() as db:
        return db.query(IdempotencyRecord).order_by(IdempotencyRecord.created_at).all()


def analyses(session_factory) -> int:
    with session_factory() as db:
        return db.query(ProductAnalysis).count()


RUN = {"category": "electronics", "max_results": 3}


# --- Misma clave, misma petición ----------------------------------------------------


def test_the_same_key_and_the_same_request_return_the_original_response_without_running_again(
    client: TestClient, session_factory
):
    first = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-1"})
    rows_after_first = analyses(session_factory)

    second = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-1"})

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert "idempotency-replayed" not in first.headers
    assert second.headers["Idempotency-Replayed"] == "true"
    assert analyses(session_factory) == rows_after_first  # no se volvió a investigar
    [record] = records(session_factory)
    assert (record.status, record.scope, record.response_status) == (COMPLETED, "research.run", 201)


def test_the_order_of_the_fields_does_not_make_it_a_different_request(client: TestClient):
    first = client.post(
        "/api/research/runs", json={"category": "home", "max_results": 2}, headers={"Idempotency-Key": "k-2"}
    )

    second = client.post(
        "/api/research/runs", json={"max_results": 2, "category": "home"}, headers={"Idempotency-Key": "k-2"}
    )

    assert second.json() == first.json()


def test_the_same_key_with_another_request_is_a_conflict(client: TestClient, session_factory):
    client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-3"})
    rows = analyses(session_factory)

    other = client.post(
        "/api/research/runs", json={"category": "garden", "max_results": 3}, headers={"Idempotency-Key": "k-3"}
    )

    assert other.status_code == 409
    assert "different request" in other.json()["detail"]
    assert analyses(session_factory) == rows


def test_two_keys_are_two_runs(client: TestClient):
    first = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-a"})
    second = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-b"})

    assert first.json()["correlation_id"] != second.json()["correlation_id"]


def test_without_a_key_in_a_simulation_every_request_runs_as_before(client: TestClient, session_factory):
    first = client.post("/api/research/runs", json=RUN)
    second = client.post("/api/research/runs", json=RUN)

    assert first.json()["correlation_id"] != second.json()["correlation_id"]
    assert records(session_factory) == []  # no se inventa una clave


# --- Alcance ------------------------------------------------------------------------


def test_the_same_key_in_two_operations_does_not_collide(client: TestClient, session_factory):
    run = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "shared"})
    product_id = run.json()["candidates"][0]["product_id"]

    legal = client.post(
        "/api/legal/runs", json={"product_id": product_id, "market": "us"}, headers={"Idempotency-Key": "shared"}
    )

    assert run.status_code == 201 and legal.status_code == 201
    assert {r.scope for r in records(session_factory)} == {"research.run", "legal.run"}


def test_the_same_key_for_two_people_does_not_collide(session_factory):
    with session_factory() as db:
        service = IdempotencyService(db)
        mine = service.claim(scope="research.run", actor=actor_scope(OWNER), key="k", payload={"a": 1})
        theirs = service.claim(scope="research.run", actor=actor_scope(OTHER), key="k", payload={"a": 1})

    assert isinstance(mine, IdempotencyRecord) and isinstance(theirs, IdempotencyRecord)
    assert mine.id != theirs.id


# --- Obligatoria cuando algo puede salir ---------------------------------------------


def test_the_key_is_required_when_the_deployment_can_reach_the_outside(client: TestClient, session_factory):
    app.dependency_overrides[get_settings] = lambda: REAL

    response = client.post("/api/research/runs", json=RUN)

    assert response.status_code == 428
    assert "Idempotency-Key" in response.json()["detail"]
    assert records(session_factory) == []


def test_a_malformed_key_is_refused(client: TestClient):
    response = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "has spaces"})

    assert response.status_code in (400, 422)


def test_validated_key_rules():
    assert validated_key(None, SETTINGS) is None
    assert validated_key("  ", SETTINGS) is None
    assert validated_key("ok-1.2_3:4", SETTINGS) == "ok-1.2_3:4"
    with pytest.raises(ValidationError):
        validated_key("x" * 129, SETTINGS)
    with pytest.raises(IdempotencyKeyRequiredError):
        validated_key(None, REAL)


# --- Qué libera la clave y qué la bloquea --------------------------------------------


def test_a_refusal_that_did_nothing_gives_the_key_back(client: TestClient, session_factory):
    refused = client.post("/api/exchange-rates/refresh", headers={"Idempotency-Key": "fx-1"})

    assert refused.status_code == 409  # la fuente no está configurada: no se hizo nada
    assert records(session_factory) == []  # la clave vuelve a servir


def test_a_failure_that_does_not_say_whether_it_took_effect_blocks_the_key(
    client: TestClient, session_factory, monkeypatch
):
    calls = {"n": 0}

    def explodes(self, **kwargs):
        calls["n"] += 1
        raise RuntimeError("connection reset after the write")

    monkeypatch.setattr(ResearchService, "run_research", explodes)

    first = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-boom"})
    second = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-boom"})

    assert first.status_code == 500
    assert second.status_code == 409
    assert "does not say whether it took effect" in second.json()["detail"]
    assert calls["n"] == 1  # no se volvió a ejecutar
    [record] = records(session_factory)
    assert record.status == UNKNOWN_OUTCOME
    assert "RuntimeError" in (record.error or "")


def test_a_request_still_in_progress_is_never_run_again(client: TestClient, session_factory):
    with session_factory() as db:  # alguien reclamó la clave y no ha terminado
        IdempotencyService(db).claim(
            scope="research.run",
            actor=actor_scope(LOCAL_ACTOR),
            key="k-busy",
            payload=ResearchRunCreate(**RUN).model_dump(),
        )
    rows = analyses(session_factory)

    again = client.post("/api/research/runs", json=RUN, headers={"Idempotency-Key": "k-busy"})

    assert again.status_code == 409
    assert "still being processed" in again.json()["detail"]
    assert analyses(session_factory) == rows


# --- Sin caducidad ------------------------------------------------------------------


def test_an_unfinished_key_does_not_become_available_with_time(session_factory):
    with session_factory() as db:
        service = IdempotencyService(db)
        stuck = service.claim(scope="fx.refresh", actor=actor_scope(OWNER), key="k-old", payload={"a": 1})
        assert isinstance(stuck, IdempotencyRecord)
        stuck.created_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=400)
        db.commit()

        with pytest.raises(IdempotencyInProgressError):
            service.claim(scope="fx.refresh", actor=actor_scope(OWNER), key="k-old", payload={"a": 1})


# --- El servicio, sin HTTP ----------------------------------------------------------


class Out(BaseModel):
    value: int


def run(db: Session, key: str | None, work, *, payload=None, actor: Actor = OWNER, settings: Settings = SETTINGS):
    return run_idempotent(
        db,
        scope="test.op",
        identity=actor,
        client_key=key,
        settings=settings,
        payload=payload if payload is not None else {"x": 1},
        response=Response(),
        status_code=201,
        response_model=Out,
        work=work,
    )


def test_work_runs_once_per_key_and_the_replay_is_the_stored_body(session_factory):
    calls = []

    def work():
        calls.append(1)
        return Out(value=len(calls))

    with session_factory() as db:
        first = run(db, "k", work)
        second = run(db, "k", work)

    assert first == Out(value=1)
    assert second == {"value": 1}
    assert len(calls) == 1


def test_a_domain_refusal_releases_and_the_next_attempt_runs(session_factory):
    attempts = []

    def work():
        attempts.append(1)
        if len(attempts) == 1:
            raise NotFoundError("not there yet")
        return Out(value=7)

    with session_factory() as db:
        with pytest.raises(NotFoundError):
            run(db, "k", work)
        result = run(db, "k", work)

    assert result == Out(value=7)
    assert len(attempts) == 2


def test_a_result_that_cannot_be_stored_blocks_the_key_because_the_effect_happened(session_factory):
    effects = []

    def work():
        effects.append(1)
        return object()  # no se puede validar contra el modelo de respuesta

    with session_factory() as db:
        with pytest.raises(Exception):  # noqa: B017 - lo que importa es el estado en que queda la clave
            run(db, "k", work)
        with pytest.raises(IdempotencyOutcomeUnknownError):
            run(db, "k", work)

    assert len(effects) == 1


def test_the_hash_ignores_field_order_and_tells_contents_apart():
    assert request_hash({"a": 1, "b": [1, 2]}) == request_hash({"b": [1, 2], "a": 1})
    assert request_hash({"a": 1}) != request_hash({"a": 2})


def test_claim_returns_a_replay_only_once_completed(session_factory):
    with session_factory() as db:
        service = IdempotencyService(db)
        record = service.claim(scope="s", actor="a", key="k", payload={"x": 1})
        assert isinstance(record, IdempotencyRecord)
        with pytest.raises(IdempotencyInProgressError):
            service.claim(scope="s", actor="a", key="k", payload={"x": 1})

        service.complete(record, status_code=201, body={"ok": True})

        replay = service.claim(scope="s", actor="a", key="k", payload={"x": 1})
        assert replay == Replay(status_code=201, body={"ok": True})
        with pytest.raises(IdempotencyConflictError):
            service.claim(scope="s", actor="a", key="k", payload={"x": 2})
        assert db.query(IdempotencyRecord).one().status == COMPLETED


def test_the_in_progress_status_is_the_initial_one(session_factory):
    with session_factory() as db:
        record = IdempotencyService(db).claim(scope="s", actor="a", key="k", payload={})
        assert isinstance(record, IdempotencyRecord)
        assert record.status == IN_PROGRESS


# --- Decidir un objetivo reserva presupuesto: hacerlo dos veces no es un detalle ------

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
    "spend_action": "launch_marketing_campaign",
    "spend_amount": 60_000.0,
}


def spending_objective(session_factory) -> str:
    from app.budgets.service import BudgetLedgerService
    from app.core.ids import new_id
    from app.db.models.objective import Objective

    with session_factory() as db:
        BudgetLedgerService(db).authorise_budget(hard_limit=100_000.0, actor="owner@amazona.local")
        objective = Objective(id=new_id(), title="spend", created_by="owner@amazona.local", context=SPEND_CONTEXT)
        db.add(objective)
        db.commit()
        return objective.id


def reservations(session_factory) -> int:
    from app.db.models.budget import FinancialEvent

    with session_factory() as db:
        return db.query(FinancialEvent).filter_by(type="RESERVE").count()


def test_running_an_objective_twice_with_the_same_key_decides_and_reserves_once(client: TestClient, session_factory):
    objective_id = spending_objective(session_factory)

    first = client.post(f"/api/objectives/{objective_id}/run", headers={"Idempotency-Key": "obj-1"})
    second = client.post(f"/api/objectives/{objective_id}/run", headers={"Idempotency-Key": "obj-1"})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert reservations(session_factory) == 1


def test_the_same_key_on_another_objective_is_a_conflict_not_a_replay(client: TestClient, session_factory):
    objective_id = spending_objective(session_factory)
    client.post(f"/api/objectives/{objective_id}/run", headers={"Idempotency-Key": "obj-2"})

    other = client.post("/api/objectives/another-objective/run", headers={"Idempotency-Key": "obj-2"})

    assert other.status_code == 409
    assert reservations(session_factory) == 1
