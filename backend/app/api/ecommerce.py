from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.storefront import Storefront as StorefrontModel
from app.db.session import get_db
from app.ecommerce.service import EcommerceStorefrontService
from app.permissions.policies import ApiAction

router = APIRouter(tags=["ecommerce"])


class StorefrontRunCreate(BaseModel):
    product_id: str
    market: str


class StorefrontOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    market: str
    store_slug: str
    launch_status: str
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> StorefrontOut:
    storefront = db.query(StorefrontModel).filter_by(correlation_id=correlation_id).first()
    if storefront is None:
        raise NotFoundError(f"storefront run {correlation_id} not found")
    return StorefrontOut.model_validate(storefront)


@router.post("/api/ecommerce/runs", response_model=StorefrontOut, status_code=201)
def create_storefront_run(
    payload: StorefrontRunCreate,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
) -> StorefrontOut:
    correlation_id = new_correlation_id()
    EcommerceStorefrontService(db).run_generation(
        product_id=payload.product_id,
        market=payload.market,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/ecommerce/runs/{correlation_id}", response_model=StorefrontOut)
def get_storefront_run(correlation_id: str, db: Session = Depends(get_db)) -> StorefrontOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/storefronts", response_model=list[StorefrontOut])
def list_product_storefronts(product_id: str, db: Session = Depends(get_db)) -> list[StorefrontModel]:
    return (
        db.query(StorefrontModel)
        .filter_by(product_id=product_id)
        .order_by(StorefrontModel.created_at.desc())
        .all()
    )
