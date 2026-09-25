from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.marketplace_listing import MarketplaceListing as MarketplaceListingModel
from app.db.session import get_db
from app.marketplace.service import MarketplaceListingService
from app.permissions.policies import ApiAction

router = APIRouter(tags=["marketplace"])


class MarketplaceListingRunCreate(BaseModel):
    product_id: str
    market: str
    platform: str = Field(default="amazon")


class MarketplaceListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    storefront_id: str | None
    market: str
    platform: str
    listing_status: str
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> MarketplaceListingOut:
    listing = db.query(MarketplaceListingModel).filter_by(correlation_id=correlation_id).first()
    if listing is None:
        raise NotFoundError(f"marketplace listing run {correlation_id} not found")
    return MarketplaceListingOut.model_validate(listing)


@router.post("/api/marketplace/runs", response_model=MarketplaceListingOut, status_code=201)
def create_marketplace_listing_run(
    payload: MarketplaceListingRunCreate,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
) -> MarketplaceListingOut:
    correlation_id = new_correlation_id()
    MarketplaceListingService(db).run_generation(
        product_id=payload.product_id,
        market=payload.market,
        platform=payload.platform,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/marketplace/runs/{correlation_id}", response_model=MarketplaceListingOut)
def get_marketplace_listing_run(correlation_id: str, db: Session = Depends(get_db)) -> MarketplaceListingOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/marketplace-listings", response_model=list[MarketplaceListingOut])
def list_product_marketplace_listings(
    product_id: str, db: Session = Depends(get_db)
) -> list[MarketplaceListingModel]:
    return (
        db.query(MarketplaceListingModel)
        .filter_by(product_id=product_id)
        .order_by(MarketplaceListingModel.created_at.desc())
        .all()
    )
