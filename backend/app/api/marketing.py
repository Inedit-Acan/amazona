from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.marketing_campaign import MarketingCampaign as MarketingCampaignModel
from app.db.session import get_db
from app.marketing.service import MarketingCampaignService

router = APIRouter(tags=["marketing"])


class MarketingCampaignRunCreate(BaseModel):
    product_id: str
    market: str
    platform: str = Field(default="meta")
    daily_budget: float = Field(default=20.0)


class MarketingCampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    marketplace_listing_id: str | None
    market: str
    platform: str
    daily_budget: float
    campaign_status: str
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> MarketingCampaignOut:
    campaign = db.query(MarketingCampaignModel).filter_by(correlation_id=correlation_id).first()
    if campaign is None:
        raise NotFoundError(f"marketing campaign run {correlation_id} not found")
    return MarketingCampaignOut.model_validate(campaign)


@router.post("/api/marketing/runs", response_model=MarketingCampaignOut, status_code=201)
def create_marketing_campaign_run(
    payload: MarketingCampaignRunCreate, db: Session = Depends(get_db)
) -> MarketingCampaignOut:
    correlation_id = new_correlation_id()
    MarketingCampaignService(db).run_generation(
        product_id=payload.product_id,
        market=payload.market,
        platform=payload.platform,
        daily_budget=payload.daily_budget,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/marketing/runs/{correlation_id}", response_model=MarketingCampaignOut)
def get_marketing_campaign_run(correlation_id: str, db: Session = Depends(get_db)) -> MarketingCampaignOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/campaigns", response_model=list[MarketingCampaignOut])
def list_product_campaigns(product_id: str, db: Session = Depends(get_db)) -> list[MarketingCampaignModel]:
    return (
        db.query(MarketingCampaignModel)
        .filter_by(product_id=product_id)
        .order_by(MarketingCampaignModel.created_at.desc())
        .all()
    )
