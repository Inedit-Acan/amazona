import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.marketing_campaign import MarketingCampaign
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
    product = Product(name="Silicone kitchen organizer", category="home", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def test_marketing_campaign_can_be_persisted_without_a_marketplace_listing(db_session: Session):
    product = _make_product(db_session)

    campaign = MarketingCampaign(
        product_id=product.id,
        marketplace_listing_id=None,
        market="us",
        platform="google",
        daily_budget=20.0,
        campaign_status="READY",
        recommendation="GO",
        confidence=0.85,
        data={"ad_creative": {}},
        correlation_id="corr-marketing-1",
    )
    db_session.add(campaign)
    db_session.commit()

    persisted = db_session.get(MarketingCampaign, campaign.id)
    assert persisted.platform == "google"
    assert persisted.marketplace_listing_id is None


def test_marketing_campaign_requires_a_valid_product_id(db_session: Session):
    campaign = MarketingCampaign(
        product_id=new_id(),  # does not exist
        market="us",
        platform="google",
        daily_budget=20.0,
        campaign_status="READY",
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-marketing-2",
    )
    db_session.add(campaign)

    with pytest.raises(IntegrityError):
        db_session.commit()
