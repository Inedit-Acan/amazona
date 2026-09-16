import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.marketplace_listing import MarketplaceListing
from app.db.models.product import Product


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


def test_marketplace_listing_can_be_persisted_without_a_storefront(db_session: Session):
    product = _make_product(db_session)

    listing = MarketplaceListing(
        product_id=product.id,
        storefront_id=None,
        market="us",
        platform="amazon",
        listing_status="READY",
        recommendation="GO",
        confidence=0.85,
        data={"listing_content": {}},
        correlation_id="corr-marketplace-1",
    )
    db_session.add(listing)
    db_session.commit()

    persisted = db_session.get(MarketplaceListing, listing.id)
    assert persisted.platform == "amazon"
    assert persisted.storefront_id is None


def test_marketplace_listing_requires_a_valid_product_id(db_session: Session):
    listing = MarketplaceListing(
        product_id=new_id(),  # does not exist
        market="us",
        platform="amazon",
        listing_status="READY",
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-marketplace-2",
    )
    db_session.add(listing)

    with pytest.raises(IntegrityError):
        db_session.commit()
