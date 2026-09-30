"""La API de transposiciones nacionales (Milestone 43, ADR 0021).

La autorización por rol la cubren los inventarios de `test_api_authorization.py` y
`test_permission_matrix.py` (mismo permiso, `REGULATORY_WRITE`: OWNER y ADMIN);
aquí se prueba lo que la ruta hace una vez autorizada. La fuente se sustituye por
una falsa.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from national_test_support import TOYS, TOYS_ID, FakeNationalSource, toys_record
from regulatory_test_support import GPSR
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.costs.service import ApiBudgetExceededError
from app.db.base import Base
from app.db.models.national_anchor import NationalAnchor
from app.db.session import get_db
from app.integrations.regulatory.boe import NationalSourceUnavailableError
from app.legal.national import ATTRIBUTION, NOTICE
from app.legal.regulatory import RegulatoryService
from app.main import app

BODY = {
    "product_scope": "Toys",
    "jurisdiction": "eu",
    "celex": TOYS,
    "regulation": "Toy Safety Directive",
    "requirement": "Toys must be safe",
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
def source(monkeypatch):
    """La fuente del BOE falsa, con la fuente real «configurada»."""
    fake = FakeNationalSource({TOYS_ID: toys_record(when=datetime.datetime.now(datetime.UTC))})
    monkeypatch.setattr(RegulatoryService, "_resolve_national_source", lambda self, cid: fake)
    return fake


def declare_requirement(client, **overrides):
    return client.post("/api/regulatory-requirements", json={**BODY, **overrides})


def declare_transposition(client, requirement_id, national_id=TOYS_ID, **extra):
    return client.post(
        f"/api/regulatory-requirements/{requirement_id}/national-transpositions",
        json={"national_id": national_id, **extra},
    )


def listed(client):
    return client.get("/api/regulatory-requirements").json()[0]


# --- Declarar ---------------------------------------------------------------------


def test_a_declared_transposition_is_listed_as_declared_with_no_anchor_and_the_notice(client):
    requirement = declare_requirement(client).json()

    created = declare_transposition(client, requirement["id"], note="RD juguetes")

    assert created.status_code == 201
    body = created.json()
    assert body["national_id"] == TOYS_ID
    assert body["provenance"] == "declared"
    assert body["anchor"] is None
    assert body["assessment"]["state"] == "never_checked"
    assert body["assessment"]["ok"] is False
    assert body["official_url"] == "https://www.boe.es/buscar/doc.php?id=BOE-A-2011-14252"
    assert body["notice"] == NOTICE and body["attribution"] == ATTRIBUTION
    nested = listed(client)["national_transpositions"]
    assert [t["national_id"] for t in nested] == [TOYS_ID]


def test_the_free_text_field_of_milestone_41_is_still_returned(client):
    requirement = declare_requirement(
        client, transposition_reference="Real Decreto 1205/2011", transposition_provenance="declared"
    )

    assert requirement.json()["transposition_reference"] == "Real Decreto 1205/2011"
    assert requirement.json()["national_transpositions"] == []


@pytest.mark.parametrize("bad", ["Real Decreto 1205/2011", "", "DOUE-L-2009-81173", "BOE-A-11-1"])
def test_an_identifier_that_is_not_a_boe_id_is_a_422(client, bad):
    requirement = declare_requirement(client).json()

    assert declare_transposition(client, requirement["id"], bad).status_code == 422


def test_a_regulation_cannot_have_a_transposition(client):
    requirement = declare_requirement(client, celex=GPSR).json()

    response = declare_transposition(client, requirement["id"])

    assert response.status_code == 422
    assert "not a directive" in response.json()["detail"]


def test_declaring_the_same_norm_twice_or_for_a_missing_requirement_is_refused(client):
    requirement = declare_requirement(client).json()
    declare_transposition(client, requirement["id"])

    assert declare_transposition(client, requirement["id"]).status_code == 422
    assert declare_transposition(client, "missing").status_code == 404


# --- Verificar --------------------------------------------------------------------


def test_verify_stores_what_the_source_said_and_the_listing_shows_every_layer(client, source):
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    response = client.post(f"/api/national-transpositions/{transposition['id']}/verify")

    assert response.status_code == 200
    body = response.json()
    assert source.asked == [TOYS_ID]
    anchor = body["anchor"]
    # Capa: la fuente. Verbatim, informativa y con su atribución.
    assert anchor["provenance"] == "third_party_verified"
    assert anchor["informational"] is True
    assert anchor["notice"] == NOTICE and anchor["attribution"] == ATTRIBUTION
    assert anchor["consolidated"] is True
    assert anchor["source_metadata"]["estatus_derogacion"] == "N"
    assert anchor["source_metadata"]["fecha_vigencia"] == "20110901"
    assert anchor["source_updated_at"] == anchor["source_metadata"]["fecha_actualizacion"]
    # Capa: publicación oficial, aparte de lo consolidado.
    assert anchor["publication_state"] == "confirmed"
    assert anchor["publication_url"].endswith("BOE-A-2011-14252")
    # Capa: relación con la norma UE, con la relación de la fuente tal cual.
    assessment = body["assessment"]
    assert assessment["state"] == "verified_in_force"
    assert assessment["corroboration"] == "corroborated"
    assert assessment["ok"] is True
    (match,) = assessment["matching_relations"]
    assert match["relation"] == "TRANSPONE" and match["relation_code"] == 426
    assert "Directiva 2009/48/CE" in match["text"]
    assert listed(client)["national_transpositions"][0]["assessment"]["ok"] is True


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (NationalSourceUnavailableError("the BOE did not answer"), 502),
        (NationalSourceUnavailableError("the BOE answered HTTP 500"), 502),
        (ApiBudgetExceededError("no room"), 429),
    ],
)
def test_source_failures_map_to_502_and_429_and_store_nothing(
    client, session_factory, monkeypatch, failure, status
):
    fake = FakeNationalSource({TOYS_ID: failure})
    monkeypatch.setattr(RegulatoryService, "_resolve_national_source", lambda self, cid: fake)
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    response = client.post(f"/api/national-transpositions/{transposition['id']}/verify")

    assert response.status_code == status
    assert session_factory().query(NationalAnchor).count() == 0
    assert listed(client)["national_transpositions"][0]["anchor"] is None


def test_verify_without_a_real_source_is_a_409_and_stores_nothing(client, session_factory):
    """Por defecto `NATIONAL_LAW_PROVIDER` es `mock`: no se llama a nadie."""
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    response = client.post(f"/api/national-transpositions/{transposition['id']}/verify")

    assert response.status_code == 409
    assert "NATIONAL_LAW_PROVIDER" in response.json()["detail"]
    assert session_factory().query(NationalAnchor).count() == 0


def test_verify_of_an_unknown_transposition_is_a_404(client):
    assert client.post("/api/national-transpositions/nope/verify").status_code == 404
    assert client.post("/api/national-transpositions/nope/withdraw").status_code == 404


def test_a_not_consolidated_norm_is_listed_as_such_and_never_as_nonexistent(client, monkeypatch):
    fake = FakeNationalSource({TOYS_ID: toys_record(when=datetime.datetime.now(datetime.UTC), consolidated=False)})
    monkeypatch.setattr(RegulatoryService, "_resolve_national_source", lambda self, cid: fake)
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    body = client.post(f"/api/national-transpositions/{transposition['id']}/verify").json()

    assert body["anchor"]["consolidated"] is False
    assert body["assessment"]["state"] == "not_consolidated"
    assert body["assessment"]["ok"] is False
    assert "does not say the norm does not exist" in body["assessment"]["reasons"][0]


def test_a_repealed_norm_is_shown_with_the_source_flags_and_asks_for_review(client, monkeypatch):
    fake = FakeNationalSource(
        {
            TOYS_ID: toys_record(
                when=datetime.datetime.now(datetime.UTC),
                metadata={"estatus_derogacion": "S", "fecha_derogacion": "20300101"},
            )
        }
    )
    monkeypatch.setattr(RegulatoryService, "_resolve_national_source", lambda self, cid: fake)
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    body = client.post(f"/api/national-transpositions/{transposition['id']}/verify").json()

    assert body["assessment"]["state"] == "not_in_force"
    assert body["anchor"]["source_metadata"]["fecha_derogacion"] == "20300101"


# --- Retirar ------------------------------------------------------------------------


def test_withdrawing_removes_it_from_the_listing(client):
    requirement = declare_requirement(client).json()
    transposition = declare_transposition(client, requirement["id"]).json()

    response = client.post(f"/api/national-transpositions/{transposition['id']}/withdraw")

    assert response.status_code == 200
    assert listed(client)["national_transpositions"] == []
    assert client.post(f"/api/national-transpositions/{transposition['id']}/withdraw").status_code == 422


def test_the_default_configuration_keeps_the_national_provider_on_mock():
    assert Settings(_env_file=None).national_law_provider.value == "mock"
