"""`GET /api/approvals` expone `requested_at` y `correlation_id` (Commit 6a del Director ejecutivo).

Los dos campos existían en la tabla `approvals` (ambos `NOT NULL`: `requested_at` es `timestamptz` con valor por defecto
«ahora en UTC» y `correlation_id` es el UUID de la ejecución del CEO que la pidió) y no salían por la API. El cambio es
ADITIVO: ningún campo existente cambia de nombre, tipo ni valor; el orden y el filtrado de la lista siguen siendo los de
siempre; los dos campos nuevos también salen en las respuestas de `approve` y `reject` (comparten el modelo de salida).

Se prueba en SQLite (que descarta la zona al leer) y en PostgreSQL (`timestamptz`): `requested_at` debe salir SIEMPRE
con zona, y por tanto el mismo instante en los dos. En PostgreSQL solo si hay uno local o efímero alcanzable.
"""

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.budgets.service import BudgetLedgerService
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.decision import Decision
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.session import get_db
from app.main import app

UTC = datetime.UTC
T0 = datetime.datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)
OLD_FIELDS = {"id", "decision_id", "action", "amount", "status", "expires_at", "resolved_at", "resolved_by"}
NEW_FIELDS = {"requested_at", "correlation_id"}


class OldClientApproval(BaseModel):
    """Lo que leía un cliente de ANTES del cambio: solo los campos antiguos, y los extra se ignoran."""

    model_config = ConfigDict(extra="ignore")

    id: str
    decision_id: str
    action: str
    amount: float | None
    status: str
    expires_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    resolved_by: str | None


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def engine(request):
    """Una base por módulo y backend (una por prueba tardaría minutos); cada prueba la vacía."""
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
        for model in (AuditLog, Approval, Decision, Project, Objective):
            session.query(model).delete()
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
    """Siembra aprobaciones con su cadena objetivo → proyecto → decisión. Devuelve los ids en el orden de inserción."""

    def add(rows: list[dict]) -> list[str]:
        ids: list[str] = []
        with session_factory() as session:
            for index, row in enumerate(rows):
                objective = Objective(title=f"obj {index}", created_by="seed", status="RECEIVED")
                session.add(objective)
                session.flush()
                project = Project(objective_id=objective.id, name=f"proj {index}", status="VALIDATING")
                session.add(project)
                session.flush()
                decision = Decision(
                    project_id=project.id, status="HUMAN_APPROVAL", correlation_id=row.get("correlation_id", "c" * 36)
                )
                session.add(decision)
                session.flush()
                approval = Approval(
                    decision_id=decision.id,
                    action=row.get("action", "launch_marketing_campaign"),
                    amount=row.get("amount", 120.0),
                    status=row.get("status", "PENDING"),
                    requested_at=row.get("requested_at", T0),
                    expires_at=row.get("expires_at", datetime.datetime.now(UTC) + datetime.timedelta(hours=24)),
                    correlation_id=row.get("correlation_id", str(uuid.uuid4())),
                )
                session.add(approval)
                session.flush()
                ids.append(approval.id)
            session.commit()
        return ids

    return add


def instant(text: str) -> datetime.datetime:
    """El instante de un campo NUEVO: tiene que salir con zona, también en SQLite."""
    value = datetime.datetime.fromisoformat(text)
    assert value.tzinfo is not None, f"{text!r} sale SIN zona"
    return value.astimezone(UTC)


def loose(text: str) -> datetime.datetime:
    """El instante de un campo ANTIGUO (`expires_at`): SQLite lo devuelve sin zona (UTC) y eso no cambia."""
    value = datetime.datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# --- los dos campos salen -------------------------------------------------------------------------


def test_every_approval_carries_requested_at_and_correlation_id(client, seed):
    corr = [str(uuid.uuid4()) for _ in range(3)]
    seed([{"correlation_id": c, "requested_at": T0 + datetime.timedelta(minutes=i)} for i, c in enumerate(corr)])
    rows = client.get("/api/approvals").json()
    assert len(rows) == 3
    for row in rows:
        assert NEW_FIELDS <= set(row), set(row)
    assert sorted(row["correlation_id"] for row in rows) == sorted(corr)


def test_correlation_id_keeps_its_format_it_is_the_uuid_that_was_stored(client, seed):
    corr = str(uuid.uuid4())
    seed([{"correlation_id": corr}])
    value = client.get("/api/approvals").json()[0]["correlation_id"]
    assert value == corr and len(value) == 36
    assert str(uuid.UUID(value)) == value


def test_requested_at_always_has_a_zone_and_is_the_stored_instant_to_the_microsecond(client, seed):
    seed([{"requested_at": T0}, {"requested_at": T0 + datetime.timedelta(days=3, microseconds=7)}])
    rows = client.get("/api/approvals").json()
    got = sorted(instant(row["requested_at"]) for row in rows)
    assert got == [T0, T0 + datetime.timedelta(days=3, microseconds=7)]


def test_requested_at_is_not_the_expiry_nor_the_resolution(client, seed):
    seed([{"requested_at": T0, "expires_at": T0 + datetime.timedelta(hours=24)}])
    row = client.get("/api/approvals").json()[0]
    assert instant(row["requested_at"]) == T0
    assert loose(row["expires_at"]) == T0 + datetime.timedelta(hours=24) != instant(row["requested_at"])
    assert row["resolved_at"] is None


# --- compatibilidad hacia atrás -------------------------------------------------------------------


def test_the_old_fields_are_all_still_there_with_the_same_values(client, seed):
    seed(
        [
            {"action": "refund", "amount": 15.5, "status": "PENDING"},
            {"action": "x", "amount": None, "status": "REJECTED"},
        ]
    )
    rows = client.get("/api/approvals").json()
    assert all(OLD_FIELDS <= set(row) for row in rows)
    assert {row["action"] for row in rows} == {"refund", "x"}
    assert {row["amount"] for row in rows} == {15.5, None}
    assert {row["status"] for row in rows} == {"PENDING", "REJECTED"}
    assert all(set(row) == OLD_FIELDS | NEW_FIELDS for row in rows), "ni un campo más ni uno menos"


def test_an_old_client_that_only_knows_the_old_fields_still_parses_the_response(client, seed):
    seed([{}, {"status": "APPROVED"}])
    for row in client.get("/api/approvals").json():
        OldClientApproval.model_validate(row)


def test_order_and_filtering_are_those_of_before_every_row_in_the_natural_order(client, seed, session_factory):
    minutes = [2, 0, 3, 1, 4]  # ni ascendente ni descendente por `requested_at`: un ORDER BY nuevo se notaría
    statuses = ["PENDING", "APPROVED", "EXPIRED", "REJECTED", "PENDING"]
    seed(
        [
            {"status": st, "requested_at": T0 + datetime.timedelta(minutes=m)}
            for st, m in zip(statuses, minutes, strict=True)
        ]
    )
    with session_factory() as session:
        natural = [row.id for row in session.query(Approval).all()]
    assert len(natural) == 5, "no se filtra por estado ni se pagina"
    assert [row["id"] for row in client.get("/api/approvals").json()] == natural


def test_expired_and_resolved_rows_are_still_listed(client, seed):
    past = datetime.datetime(2020, 1, 1, tzinfo=UTC)
    seed([{"status": "PENDING", "expires_at": past, "requested_at": past - datetime.timedelta(hours=24)}])
    rows = client.get("/api/approvals").json()
    assert len(rows) == 1 and rows[0]["status"] == "PENDING"


def test_the_nullable_old_fields_stay_nullable(client, seed):
    seed([{"expires_at": None, "amount": None}])
    row = client.get("/api/approvals").json()[0]
    assert (
        row["expires_at"] is None
        and row["amount"] is None
        and row["resolved_at"] is None
        and row["resolved_by"] is None
    )
    assert instant(row["requested_at"]) == T0


def test_an_empty_table_is_an_empty_list(client):
    response = client.get("/api/approvals")
    assert response.status_code == 200 and response.json() == []


# --- approve y reject comparten el modelo de salida -----------------------------------------------


@pytest.mark.parametrize("verb", ["approve", "reject"])
def test_resolving_returns_the_two_fields_and_does_not_touch_them(client, seed, verb):
    corr = str(uuid.uuid4())
    (approval_id,) = seed([{"correlation_id": corr, "requested_at": T0, "amount": None}])
    response = client.post(f"/api/approvals/{approval_id}/{verb}", json={"actor": "owner@amazona.local"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == OLD_FIELDS | NEW_FIELDS
    assert body["correlation_id"] == corr
    assert instant(body["requested_at"]) == T0
    assert body["status"] == ("APPROVED" if verb == "approve" else "REJECTED")
    listed = client.get("/api/approvals").json()[0]
    assert listed["correlation_id"] == corr and instant(listed["requested_at"]) == T0


def test_the_correlation_id_links_the_approval_to_its_audit_trail(client, seed, session_factory):
    corr = str(uuid.uuid4())
    (approval_id,) = seed([{"correlation_id": corr, "amount": None}])
    client.post(f"/api/approvals/{approval_id}/approve", json={"actor": "owner@amazona.local"})
    with session_factory() as session:
        entries = session.query(AuditLog).filter(AuditLog.correlation_id == corr).all()
    assert [entry.action for entry in entries] == ["approval.approve"]
    assert client.get("/api/approvals").json()[0]["correlation_id"] == corr


def test_a_real_run_of_the_ceo_exposes_the_decision_correlation_id(client, session_factory):
    context = {
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
        "spend_amount": 150.0,
    }
    objective_id = client.post(
        "/api/objectives", json={"title": "Validate", "created_by": "owner@amazona.local", "context": context}
    ).json()["id"]
    with session_factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=100_000.0, actor="owner@amazona.local")
    decision = client.post(f"/api/objectives/{objective_id}/run").json()
    approvals = client.get("/api/approvals").json()
    assert len(approvals) == 1
    assert approvals[0]["correlation_id"] == decision["correlation_id"]
    assert instant(approvals[0]["requested_at"]) < loose(approvals[0]["expires_at"])
