from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    agents,
    approvals,
    audit,
    decisions,
    ecommerce,
    economics,
    legal,
    marketing,
    marketplace,
    monitoring,
    objectives,
    products,
    projects,
    research,
    sourcing,
    tasks,
)
from app.approvals.service import ApprovalNotPendingError
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.core.logging import configure_logging, set_correlation_id
from app.db.session import get_db

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="AMAZONA Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CORRELATION_ID_HEADER = "X-Correlation-ID"


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ApprovalNotPendingError)
async def approval_not_pending_handler(request: Request, exc: ApprovalNotPendingError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get(CORRELATION_ID_HEADER, new_correlation_id())
    set_correlation_id(correlation_id)

    response = await call_next(request)
    response.headers[CORRELATION_ID_HEADER] = correlation_id
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "amazona-backend"}


@app.get("/health/detailed")
def health_detailed(db: Session = Depends(get_db)) -> JSONResponse:
    """Operational status: DB connectivity, applied migration, whether
    Supabase is configured. Never includes credentials."""
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - only a failure to reach the DB at all means "database unreachable"
        return JSONResponse(
            status_code=503,
            content={"database": "error", "migration": None, "supabase_configured": settings.is_supabase_configured},
        )

    try:
        # Absent in ad-hoc test/dev databases created via Base.metadata
        # rather than `alembic upgrade head` — that's a missing migration
        # record, not a reason to report the database itself as down.
        migration = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        db.rollback()  # reset any aborted transaction state (Postgres) before the session is reused/closed
        migration = None

    return JSONResponse(
        content={
            "database": "ok",
            "migration": migration,
            "supabase_configured": settings.is_supabase_configured,
        }
    )


app.include_router(objectives.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(agents.router)
app.include_router(decisions.router)
app.include_router(approvals.router)
app.include_router(audit.router)
app.include_router(monitoring.router)
app.include_router(research.router)
app.include_router(products.router)
app.include_router(sourcing.router)
app.include_router(economics.router)
app.include_router(legal.router)
app.include_router(ecommerce.router)
app.include_router(marketplace.router)
app.include_router(marketing.router)
