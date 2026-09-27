"""Lo que la lista de productos dice sobre la identidad (Milestone 36, ADR 0014).

La pantalla de Investigación lee de aquí, y tiene que poder decir «este producto
también llegó con este otro nombre, y se unieron por esta vía». Una fusión que no
se ve es indistinguible de un error.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.product import Product
from app.db.models.product_identity_alias import ProductIdentityAlias
from app.db.session import get_db
from app.main import app


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
def client(session_factory):
    return TestClient(app)


def test_a_product_publishes_its_identity(client: TestClient):
    client.post("/api/research/runs", json={"category": "home", "max_results": 2})

    products = client.get("/api/products").json()

    assert products
    assert all(product["identity_key"] for product in products)


def test_a_product_that_never_changed_name_has_no_aliases(client: TestClient):
    """Vacío porque no hubo nada que resolver, no porque falte el dato."""
    client.post("/api/research/runs", json={"category": "home", "max_results": 2})

    products = client.get("/api/products").json()

    assert all(product["also_known_as"] == [] for product in products)


def test_the_other_names_come_with_their_reason(client: TestClient, session_factory):
    session = session_factory()
    product = Product(
        name="Air fryer",
        identity_key="air fryer",
        category="home",
        status="CANDIDATE",
        created_by="owner@amazona.local",
        source="manual",
    )
    session.add(product)
    session.flush()
    session.add_all(
        [
            ProductIdentityAlias(
                product_id=product.id,
                alias="airfryer",
                identity_key="air fryer",
                method="alias:v1",
                correlation_id="cid-1",
            ),
            # El mismo nombre en dos ejecuciones distintas se enseña una vez.
            ProductIdentityAlias(
                product_id=product.id,
                alias="airfryer",
                identity_key="air fryer",
                method="alias:v1",
                correlation_id="cid-2",
            ),
            ProductIdentityAlias(
                product_id=product.id,
                alias="AIR FRYER",
                identity_key="air fryer",
                method="normalised",
                correlation_id="cid-2",
            ),
        ]
    )
    session.commit()
    session.close()

    [listed] = client.get("/api/products").json()

    assert listed["also_known_as"] == [
        {"alias": "airfryer", "method": "alias:v1"},
        {"alias": "AIR FRYER", "method": "normalised"},
    ]


def test_an_empty_catalogue_asks_for_no_aliases(client: TestClient):
    assert client.get("/api/products").json() == []
