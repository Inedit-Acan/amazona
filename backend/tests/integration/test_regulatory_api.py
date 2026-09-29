"""La API de requisitos regulatorios, comprobación y evidencia (Milestone 41).

La autorización por rol la cubren los inventarios de
`test_api_authorization.py` y `test_api_read_authorization.py`; aquí se prueba lo
que la ruta hace una vez autorizada. La fuente se sustituye por una falsa."""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.product import Product
from app.db.session import get_db
from app.integrations.regulatory.eur_lex import AnchorUnavailableError
from app.legal.regulatory import RegulatoryService
from app.main import app
from tests.integration.test_regulatory_service import GPSR, FakeSource, anchor

BODY = {
    "product_scope": "Toys",
    "jurisdiction": "eu",
    "celex": GPSR,
    "regulation": "General Product Safety Regulation",
    "requirement": "A documented safety assessment must exist",
    "kind": "obligation",
}


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
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def fake_source(monkeypatch):
    source = FakeSource({GPSR: anchor(GPSR, when=datetime.datetime.now(datetime.UTC))})
    monkeypatch.setattr(RegulatoryService, "_resolve_source", lambda self, correlation_id: source)
    return source


def declare(client, **overrides):
    return client.post("/api/regulatory-requirements", json={**BODY, **overrides})


def test_a_declared_requirement_is_listed_with_its_provenance_and_no_anchor_yet(client):
    created = declare(client)

    assert created.status_code == 201
    listed = client.get("/api/regulatory-requirements").json()
    assert len(listed) == 1
    assert listed[0]["applicability_provenance"] == "declared"
    assert listed[0]["anchor"] is None
    # Nunca comprobada: se dice, no se supone vigente.
    assert listed[0]["existence"] == "never_checked"


def test_nothing_declared_means_an_empty_list(client):
    assert client.get("/api/regulatory-requirements").json() == []


@pytest.mark.parametrize(
    "bad",
    [
        {"jurisdiction": "es"},
        {"celex": "not-a-celex"},
        {"applicability_provenance": "simulated"},
        {"applicability_provenance": "third_party_verified"},
        {"kind": "advice"},
        {"requirement": "   "},
    ],
)
def test_the_api_refuses_what_is_not_a_declarable_legal_fact(client, bad):
    assert declare(client, **bad).status_code in (422, 400)


def test_superseding_replaces_the_requirement_in_the_active_list(client):
    old = declare(client).json()

    new = client.post(
        f"/api/regulatory-requirements/{old['id']}/supersede",
        json={**BODY, "requirement": "Updated text"},
    )

    assert new.status_code == 201
    listed = client.get("/api/regulatory-requirements").json()
    assert [r["id"] for r in listed] == [new.json()["id"]]


def test_a_withdrawn_requirement_leaves_the_active_list(client):
    created = declare(client).json()

    assert client.post(f"/api/regulatory-requirements/{created['id']}/withdraw").status_code == 200
    assert client.get("/api/regulatory-requirements").json() == []


def test_an_unknown_requirement_is_a_404(client):
    assert client.post("/api/regulatory-requirements/nope/withdraw").status_code == 404
    assert client.post("/api/regulatory-requirements/nope/verify").status_code == 404


def test_verify_stores_the_anchor_and_the_list_shows_the_existence_state(client, fake_source):
    created = declare(client).json()

    verified = client.post(f"/api/regulatory-requirements/{created['id']}/verify")

    assert verified.status_code == 200
    assert verified.json()["provenance"] == "third_party_verified"
    assert verified.json()["in_force"] is True
    listed = client.get("/api/regulatory-requirements").json()[0]
    assert listed["existence"] == "verified_in_force"
    assert listed["anchor"]["provider"] == "eur-lex-cellar"


def test_verify_without_a_real_source_is_a_409_and_stores_nothing(client, monkeypatch):
    monkeypatch.setattr("app.legal.regulatory.get_settings", lambda: Settings())
    created = declare(client).json()

    response = client.post(f"/api/regulatory-requirements/{created['id']}/verify")

    assert response.status_code == 409
    assert client.get("/api/regulatory-requirements").json()[0]["anchor"] is None


def test_a_source_that_does_not_answer_is_a_502_and_nothing_is_stored(client, monkeypatch):
    failing = FakeSource({GPSR: AnchorUnavailableError("down")})
    monkeypatch.setattr(RegulatoryService, "_resolve_source", lambda self, cid: failing)
    created = declare(client).json()

    response = client.post(f"/api/regulatory-requirements/{created['id']}/verify")

    assert response.status_code == 502
    assert client.get("/api/regulatory-requirements").json()[0]["existence"] == "never_checked"


def test_evidence_is_declared_for_a_product_and_listed(client, session_factory):
    with session_factory() as db:
        product = Product(name="Train", category="Toys", created_by="owner")
        db.add(product)
        db.commit()
        product_id = product.id
    requirement = declare(client).json()

    created = client.post(
        f"/api/products/{product_id}/compliance-evidence",
        json={"requirement_id": requirement["id"], "reference": "certificate 42"},
    )

    assert created.status_code == 201
    assert created.json()["provenance"] == "declared"
    listed = client.get(f"/api/products/{product_id}/compliance-evidence").json()
    assert [e["reference"] for e in listed] == ["certificate 42"]


def test_third_party_evidence_without_an_issuer_is_refused(client, session_factory):
    with session_factory() as db:
        product = Product(name="Train", category="Toys", created_by="owner")
        db.add(product)
        db.commit()
        product_id = product.id
    requirement = declare(client).json()

    response = client.post(
        f"/api/products/{product_id}/compliance-evidence",
        json={"requirement_id": requirement["id"], "provenance": "third_party_verified"},
    )

    assert response.status_code == 422


def test_evidence_for_an_unknown_product_is_a_404(client):
    requirement = declare(client).json()

    response = client.post(
        "/api/products/nope/compliance-evidence", json={"requirement_id": requirement["id"]}
    )

    assert response.status_code == 404
