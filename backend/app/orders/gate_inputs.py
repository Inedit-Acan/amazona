"""Lo que el ActionGate necesita saber de un pedido (Milestone 44, ADR 0028 §7).

En el pipeline, el gate lee las recomendaciones de los pasos de análisis de **esa** ejecución. Un pedido no pertenece
a ninguna ejecución: aquí se lee lo último que se analizó de **sus productos**. Con varios productos manda el peor
(`NO_GO` antes que `REVIEW` antes que `GO`).

Una recomendación ausente no se inventa: es `None` y el gate no la juzga. Pero **la ausencia de información no es un
permiso** (ADR 0023): fuera de una simulación, vender algo que nunca se analizó legalmente exige que alguien lo mire,
así que el servicio lo para antes de llegar al gate en vez de dejarlo pasar por no tener nada que objetar.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.order import Order
from app.orders.errors import OperationNotAllowedError

_SEVERITY = {"GO": 0, "REVIEW": 1, "NO_GO": 2}


@dataclass(frozen=True)
class OrderRecommendations:
    legal: str | None
    economics: str | None
    #: Productos del pedido sin ningún análisis legal.
    products_without_legal: tuple[str, ...]


def _worst(values: list[str]) -> str | None:
    known = [v for v in values if v in _SEVERITY]
    return max(known, key=_SEVERITY.__getitem__) if known else None


def recommendations_for(db: Session, order: Order) -> OrderRecommendations:
    product_ids = sorted({item.product_id for item in order.items})
    legal: list[str] = []
    economics: list[str] = []
    missing: list[str] = []
    for product_id in product_ids:
        latest_legal = db.scalars(
            select(LegalAnalysis)
            .where(LegalAnalysis.product_id == product_id, LegalAnalysis.market == order.market)
            .order_by(LegalAnalysis.created_at.desc())
            .limit(1)
        ).first()
        if latest_legal is None:
            missing.append(product_id)
        else:
            legal.append(latest_legal.recommendation)
        latest_economics = db.scalars(
            select(EconomicAnalysis)
            .where(EconomicAnalysis.product_id == product_id)
            .order_by(EconomicAnalysis.created_at.desc())
            .limit(1)
        ).first()
        if latest_economics is not None:
            economics.append(latest_economics.recommendation)
    return OrderRecommendations(legal=_worst(legal), economics=_worst(economics), products_without_legal=tuple(missing))


def require_legal_analysis_outside_simulation(recommendations: OrderRecommendations, settings: Settings) -> None:
    """Fuera de una simulación, un producto sin análisis legal no se vende solo (la ausencia no es un permiso)."""
    if settings.operating_in_simulation or not recommendations.products_without_legal:
        return
    raise OperationNotAllowedError(
        "no legal analysis exists for "
        + ", ".join(recommendations.products_without_legal)
        + " in this market: analyse it before selling it",
        reasons=["no legal analysis for the product in this market"],
        requires_approval=True,
    )
