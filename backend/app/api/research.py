import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.product import Product as ProductModel
from app.db.models.product_analysis import ProductAnalysis as ProductAnalysisModel
from app.db.models.research_comparison import ResearchComparison as ResearchComparisonModel
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.permissions.policies import ApiAction
from app.research.comparison_service import ResearchComparisonService
from app.research.service import ResearchService

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchRunCreate(BaseModel):
    category: str
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


class ResearchCandidateOut(BaseModel):
    product_id: str
    name: str
    category: str
    opportunity_score: float | None
    confidence: float | None
    data: dict


class ResearchRunOut(BaseModel):
    correlation_id: str
    candidates: list[ResearchCandidateOut]


class ComparisonCreate(BaseModel):
    category: str
    market: str = "us"
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    market: str
    baseline_provider: str
    candidate_provider: str
    #: El informe entero: recuentos, solapamiento, cobertura por tipo de señal,
    #: confianza, disponibilidad de score y el veredicto en una línea.
    summary: dict
    correlation_id: str
    created_at: datetime.datetime


def _load_run(correlation_id: str, db: Session) -> ResearchRunOut:
    analyses = (
        db.query(ProductAnalysisModel)
        .filter_by(correlation_id=correlation_id, analysis_type="research")
        .all()
    )
    if not analyses:
        raise NotFoundError(f"research run {correlation_id} not found")

    products_by_id = {
        p.id: p
        for p in db.query(ProductModel).filter(ProductModel.id.in_([a.product_id for a in analyses])).all()
    }

    return ResearchRunOut(
        correlation_id=correlation_id,
        candidates=[
            ResearchCandidateOut(
                product_id=a.product_id,
                name=products_by_id[a.product_id].name,
                category=products_by_id[a.product_id].category,
                opportunity_score=a.opportunity_score,
                confidence=a.confidence,
                data=a.data or {},
            )
            for a in analyses
        ],
    )


@router.post("/runs", response_model=ResearchRunOut, status_code=201)
def create_research_run(
    payload: ResearchRunCreate,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ResearchRunOut:
    def work() -> ResearchRunOut:
        correlation_id = new_correlation_id()
        products = ResearchService(db).run_research(
            category=payload.category,
            keywords=payload.keywords,
            max_results=payload.max_results,
            correlation_id=correlation_id,
        )
        if not products:
            return ResearchRunOut(correlation_id=correlation_id, candidates=[])
        return _load_run(correlation_id, db)

    return run_idempotent(
        db,
        scope="research.run",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload=payload.model_dump(),
        response=response,
        status_code=201,
        response_model=ResearchRunOut,
        work=work,
    )


@router.get("/runs/{correlation_id}", response_model=ResearchRunOut)
def get_research_run(correlation_id: str, db: Session = Depends(get_db)) -> ResearchRunOut:
    return _load_run(correlation_id, db)


@router.post("/comparisons", response_model=ComparisonOut, status_code=201)
def create_research_comparison(
    payload: ComparisonCreate,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ResearchComparisonModel:
    """Contrasta lo que mide la fuente real con lo que se inventa el mock
    (Milestone 35).

    Ejecuta los dos proveedores para la misma pregunta y guarda qué produjo cada
    uno. **Se niega en `staging` y `production`**: comparar exige ejecutar el
    mock, y ahí los datos simulados no se admiten (ADR 0008). Hacer una
    excepción «solo para un informe» sería vaciar la regla.
    """
    return run_idempotent(
        db,
        scope="research.comparison",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload=payload.model_dump(),
        response=response,
        status_code=201,
        response_model=ComparisonOut,
        work=lambda: ResearchComparisonService(db).run(
            category=payload.category,
            market=payload.market,
            keywords=payload.keywords,
            max_results=payload.max_results,
            actor=identity.audit_name,
        ),
    )


@router.get("/comparisons", response_model=list[ComparisonOut])
def list_research_comparisons(db: Session = Depends(get_db)) -> list[ResearchComparisonModel]:
    return (
        db.query(ResearchComparisonModel)
        .order_by(ResearchComparisonModel.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/comparisons/{comparison_id}", response_model=ComparisonOut)
def get_research_comparison(
    comparison_id: str, db: Session = Depends(get_db)
) -> ResearchComparisonModel:
    comparison = db.get(ResearchComparisonModel, comparison_id)
    if comparison is None:
        raise NotFoundError(f"research comparison {comparison_id} not found")
    return comparison
