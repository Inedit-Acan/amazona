import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.product import Product
from app.db.models.storefront import Storefront


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_product(db_session: Session) -> Product:
    product = Product(name="Travel cable organizer", category="accessories", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def test_storefront_can_be_persisted_with_a_valid_product(db_session: Session):
    product = _make_product(db_session)

    storefront = Storefront(
        product_id=product.id,
        market="us",
        store_slug="travel-cable-organizer-store",
        launch_status="READY",
        recommendation="GO",
        confidence=0.85,
        data={"landing_page_copy": {}},
        correlation_id="corr-ecommerce-1",
    )
    db_session.add(storefront)
    db_session.commit()

    persisted = db_session.get(Storefront, storefront.id)
    assert persisted.launch_status == "READY"
    assert persisted.store_slug == "travel-cable-organizer-store"


def test_storefront_requires_a_valid_product_id(db_session: Session):
    storefront = Storefront(
        product_id=new_id(),  # does not exist
        market="us",
        store_slug="does-not-exist-store",
        launch_status="READY",
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-ecommerce-2",
    )
    db_session.add(storefront)

    with pytest.raises(IntegrityError):
        db_session.commit()
