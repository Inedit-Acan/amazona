from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.product import Product as ProductModel
from app.db.models.product_identity_alias import ProductIdentityAlias
from app.db.session import get_db

router = APIRouter(prefix="/api/products", tags=["products"])


class ProductAliasOut(BaseModel):
    """Otro nombre con el que llegó este producto (Milestone 36, ADR 0014)."""

    model_config = ConfigDict(from_attributes=True)

    alias: str
    #: `normalised` o `alias:<versión>`. Nunca por parecido: eso no existe.
    method: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    status: str
    created_by: str
    source: str
    #: Quién es este producto, independientemente de cómo se escribiera su
    #: nombre. Nulo en las filas anteriores al Milestone 36 que nadie ha vuelto
    #: a investigar.
    identity_key: str | None = None
    #: Los nombres distintos que se resolvieron a este producto, con el motivo.
    #: Vacío cuando siempre llegó igual: no hubo nada que resolver.
    also_known_as: list[ProductAliasOut] = []


@router.get("", response_model=list[ProductOut])
def list_products(status: str | None = None, db: Session = Depends(get_db)) -> list[ProductOut]:
    query = db.query(ProductModel)
    if status is not None:
        query = query.filter(ProductModel.status == status)
    products = query.order_by(ProductModel.created_at.desc()).all()

    # Una consulta para todos, no una por producto: la pantalla de Investigación
    # pide la lista entera.
    grouped: dict[str, list[ProductAliasOut]] = {}
    if products:
        rows = (
            db.query(ProductIdentityAlias)
            .filter(ProductIdentityAlias.product_id.in_([p.id for p in products]))
            .order_by(ProductIdentityAlias.created_at.asc())
            .all()
        )
        for row in rows:
            entry = ProductAliasOut(alias=row.alias, method=row.method)
            names = grouped.setdefault(row.product_id, [])
            # El mismo nombre puede llegar en varias ejecuciones; se enseña una vez.
            if not any(known.alias == entry.alias for known in names):
                names.append(entry)

    return [
        ProductOut(
            id=product.id,
            name=product.name,
            category=product.category,
            status=product.status,
            created_by=product.created_by,
            source=product.source,
            identity_key=product.identity_key,
            also_known_as=grouped.get(product.id, []),
        )
        for product in products
    ]
