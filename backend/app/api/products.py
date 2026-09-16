from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.product import Product as ProductModel
from app.db.session import get_db

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    status: str
    created_by: str
    source: str


@router.get("", response_model=list[ProductOut])
def list_products(status: str | None = None, db: Session = Depends(get_db)) -> list[ProductModel]:
    query = db.query(ProductModel)
    if status is not None:
        query = query.filter(ProductModel.status == status)
    return query.order_by(ProductModel.created_at.desc()).all()
