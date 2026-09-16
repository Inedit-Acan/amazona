from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.product import Product as ProductModel
from app.db.models.product_analysis import ProductAnalysis as ProductAnalysisModel
from app.db.session import get_db
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
def create_research_run(payload: ResearchRunCreate, db: Session = Depends(get_db)) -> ResearchRunOut:
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


@router.get("/runs/{correlation_id}", response_model=ResearchRunOut)
def get_research_run(correlation_id: str, db: Session = Depends(get_db)) -> ResearchRunOut:
    return _load_run(correlation_id, db)
