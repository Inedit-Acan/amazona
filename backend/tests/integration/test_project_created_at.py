"""M46, Commit 7: `ProjectOut.created_at` es la fecha persistida del proyecto, sin ninguna otra fuente.

Hasta este commit la API de proyectos omitía `created_at` (aunque `projects.created_at` existe, es NOT NULL y
la lista ya se ordenaba por él) y la pantalla de Proyectos tenía que deducir la fecha de inicio de la auditoría,
que solo se lee cuando el proyecto tiene decisión. Estas pruebas fijan que la fecha sale directamente de la
fila: no es `updated_at`, no es «ahora», no depende del orden y no tiene valor por defecto.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.projects import ProjectOut
from app.db.base import Base
from app.db.models.objective import Objective
from app.db.models.project import Project
from app.db.session import get_db
from app.main import app

UTC = datetime.UTC
CONTRACT_KEYS = {"id", "objective_id", "name", "status", "created_at"}

ATTRACTIVE_CONTEXT = {
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
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture()
def client(session_factory) -> TestClient:
    return TestClient(app)


def _project(
    db: Session, *, name: str, created_at: datetime.datetime, updated_at: datetime.datetime | None = None
) -> str:
    objective = Objective(title=f"objective of {name}", created_by="owner@amazona.local")
    db.add(objective)
    db.flush()
    project = Project(
        objective_id=objective.id,
        name=name,
        status="VALIDATING",
        created_at=created_at,
        updated_at=updated_at or created_at,
    )
    db.add(project)
    db.commit()
    return project.id


def _parse(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_the_contract_of_a_project_is_exactly_these_fields_and_created_at_is_required(client, session_factory):
    with session_factory() as db:
        project_id = _project(db, name="uno", created_at=datetime.datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

    assert set(client.get(f"/api/projects/{project_id}").json()) == CONTRACT_KEYS
    assert set(client.get("/api/projects").json()[0]) == CONTRACT_KEYS
    # Sin valor por defecto: una fila sin fecha no se puede serializar con una inventada.
    assert ProjectOut.model_fields["created_at"].is_required()


def test_a_project_exposes_the_date_that_was_persisted(client, session_factory):
    moment = datetime.datetime(2026, 9, 12, 10, 0, 5, tzinfo=UTC)
    with session_factory() as db:
        project_id = _project(db, name="uno", created_at=moment)

    body = client.get(f"/api/projects/{project_id}").json()

    assert _parse(body["created_at"]) == moment


def test_it_is_not_now_and_it_is_not_updated_at(client, session_factory):
    created = datetime.datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated = datetime.datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
    with session_factory() as db:
        project_id = _project(db, name="viejo", created_at=created, updated_at=updated)

    body = client.get(f"/api/projects/{project_id}").json()

    assert _parse(body["created_at"]) == created
    assert _parse(body["created_at"]) != updated
    assert _parse(body["created_at"]).year == 2020  # no es la fecha de hoy


def test_several_projects_keep_their_own_dates_whatever_the_insertion_order(client, session_factory):
    dates = {
        "tercero": datetime.datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
        "primero": datetime.datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        "cuarto": datetime.datetime(2026, 9, 4, 23, 59, 59, tzinfo=UTC),
        "segundo": datetime.datetime(2026, 9, 2, 0, 0, 1, tzinfo=UTC),
    }
    ids = {}
    with session_factory() as db:
        for name, moment in dates.items():  # insertados desordenados a propósito
            ids[name] = _project(db, name=name, created_at=moment)

    listing = client.get("/api/projects").json()

    by_id = {item["id"]: item for item in listing}
    for name, moment in dates.items():
        assert _parse(by_id[ids[name]]["created_at"]) == moment, name
        assert _parse(client.get(f"/api/projects/{ids[name]}").json()["created_at"]) == moment, name
    # La lista sigue ordenada por esa misma fecha, de la más reciente a la más antigua.
    assert [item["name"] for item in listing] == ["cuarto", "tercero", "segundo", "primero"]


def test_the_list_and_the_detail_of_a_project_agree(client, session_factory):
    with session_factory() as db:
        project_id = _project(db, name="uno", created_at=datetime.datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

    assert client.get("/api/projects").json()[0] == client.get(f"/api/projects/{project_id}").json()


def test_the_date_is_serialised_with_an_explicit_utc_zone_even_when_sqlite_drops_it(client, session_factory):
    with session_factory() as db:
        project_id = _project(db, name="uno", created_at=datetime.datetime(2026, 9, 12, 10, 0, 5, tzinfo=UTC))

    raw = client.get(f"/api/projects/{project_id}").json()["created_at"]

    # SQLite devuelve la fecha sin zona: sin la normalización llegaría «2026-09-12T10:00:05»
    # y un navegador la leería como hora local.
    assert raw.endswith("Z") or raw.endswith("+00:00"), raw
    assert _parse(raw).utcoffset() == datetime.timedelta(0)


def test_an_aware_date_in_another_zone_keeps_its_instant():
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    instant = datetime.datetime(2026, 9, 12, 12, 0, tzinfo=plus_two)

    out = ProjectOut(id="p", objective_id="o", name="n", status="DRAFT", created_at=instant)

    assert out.created_at == instant  # el mismo instante, no se reinterpreta
    assert ProjectOut(
        id="p", objective_id="o", name="n", status="DRAFT", created_at=datetime.datetime(2026, 9, 12, 10, 0)
    ).created_at == datetime.datetime(2026, 9, 12, 10, 0, tzinfo=UTC)


def test_a_project_created_by_running_an_objective_carries_its_insertion_time(client):
    before = datetime.datetime.now(UTC)
    objective_id = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_CONTEXT,
        },
    ).json()["id"]
    decision = client.post(f"/api/objectives/{objective_id}/run").json()
    after = datetime.datetime.now(UTC)

    body = client.get(f"/api/projects/{decision['project_id']}").json()

    assert before <= _parse(body["created_at"]) <= after


# --- La moneda de `finance_validation` NO existe en la fuente, y este commit no la inventa ----------------------


def test_finance_validation_declares_no_currency_and_none_is_taken_from_configuration(client):
    """`FinanceAgent` solo lee `unit_cost`, `sale_price`, `monthly_unit_sales` y `monthly_fixed_costs` de un
    `dict` libre y devuelve `margin`, `monthly_profit` y `finance_veto`: ni la entrada ni la salida tienen
    moneda. No existe una moneda global de configuración; lo más parecido es `SpendLimitSettings.currency`
    («EUR» por defecto), que es la moneda del tope de gasto de un proveedor y no puede rellenar ese hueco.
    Si algún día la evidencia declara una moneda real, este test se cambia a propósito, no por accidente."""
    from app.agents.finance import FinanceAgent

    result = FinanceAgent().run(
        {"unit_cost": 5.0, "sale_price": 20.0, "monthly_unit_sales": 300, "monthly_fixed_costs": 500.0}
    )
    assert set(result.data) == {"margin", "monthly_profit", "finance_veto"}
    assert "currency" not in result.data

    objective_id = client.post(
        "/api/objectives",
        json={
            "title": "Validate wireless earbuds opportunity",
            "created_by": "owner@amazona.local",
            "context": ATTRACTIVE_CONTEXT,
        },
    ).json()["id"]
    decision_id = client.post(f"/api/objectives/{objective_id}/run").json()["id"]
    evidence = client.get(f"/api/decisions/{decision_id}").json()["evidence"]
    finance = next(e for e in evidence if e["source"] == "finance_validation")
    assert "currency" not in finance["data"]
    assert "currency" not in client.get("/api/projects").json()[0]
