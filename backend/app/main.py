from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import (
    agents,
    approvals,
    audit,
    cfo,
    decisions,
    ecommerce,
    economics,
    incidents,
    jobs,
    legal,
    marketing,
    marketplace,
    monitoring,
    objectives,
    operations,
    pipeline,
    products,
    projects,
    research,
    sourcing,
    tasks,
)
from app.approvals.service import ApprovalNotPendingError
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import IncidentNotOpenError, NotFoundError, PipelineDisabledError, PipelineReviewNotPendingError
from app.core.ids import new_correlation_id
from app.core.logging import configure_logging, set_correlation_id
from app.db.session import get_db
from app.integrations.registry import ProviderRegistry, validate_providers
from app.permissions.policies import ApiAction

settings = get_settings()
configure_logging(settings.log_level)
# Refuses to start a staging/production process that would accept anonymous
# mutations or cannot verify a token at all (Milestone 29, ADR 0007), or that
# would take real decisions on fixture data (Milestone 30, ADR 0008).
settings.validate_for_startup()
validate_providers(settings)

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


@app.exception_handler(PipelineReviewNotPendingError)
async def pipeline_review_not_pending_handler(
    request: Request, exc: PipelineReviewNotPendingError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(PipelineDisabledError)
async def pipeline_disabled_handler(request: Request, exc: PipelineDisabledError) -> JSONResponse:
    return JSONResponse(status_code=423, content={"detail": str(exc)})


@app.exception_handler(IncidentNotOpenError)
async def incident_not_open_handler(request: Request, exc: IncidentNotOpenError) -> JSONResponse:
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
    """Liveness. Public and deliberately empty of detail: a load balancer cannot
    carry a bearer token, and a probe that reveals the schema version or which
    providers are live is a fingerprint anyone can read (Milestone 29.1)."""
    return {"status": "ok", "service": "amazona-backend"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness, also public. Says whether this process can serve traffic and
    nothing else — no version, no environment, no providers. It exists so that
    /health/detailed could stop being public without leaving the infrastructure
    without a probe."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - unreachable database is the whole question here
        return JSONResponse(status_code=503, content={"status": "degraded"})
    return JSONResponse(content={"status": "ok"})


@app.get("/health/detailed", dependencies=[Depends(authorize(ApiAction.DIAGNOSTICS_READ))])
def health_detailed(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> JSONResponse:
    """Operational status: DB connectivity, applied migration, whether Supabase
    is configured, and which provider backs each external domain. Never includes
    credentials.

    Behind identity since Milestone 29.1: together, the schema version, the
    environment and the list of simulated domains describe the deployment —
    including where its data is invented — closely enough that it should not be
    readable by anyone who can reach the port. Use /health/ready for probes."""
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
            "environment": settings.environment,
            # Which provider backs each external domain, and whether it is
            # simulated. The Estado panel can say so instead of guessing.
            "providers": [
                {"domain": b.domain, "kind": b.kind, "name": b.name, "simulated": b.is_simulated}
                for b in ProviderRegistry(settings).bindings()
            ],
        }
    )


# Read authorization (Milestone 29.1). Applied per router rather than per route
# so that a GET added later is protected by default: forgetting a decorator is
# how read endpoints quietly end up public. The mutating routes inside these
# routers keep their own, narrower ApiAction on top of this one.
BUSINESS = [Depends(authorize(ApiAction.BUSINESS_READ))]

app.include_router(objectives.router, dependencies=BUSINESS)
app.include_router(projects.router, dependencies=BUSINESS)
app.include_router(tasks.router, dependencies=BUSINESS)
app.include_router(agents.router, dependencies=BUSINESS)
app.include_router(decisions.router, dependencies=BUSINESS)
app.include_router(approvals.router, dependencies=BUSINESS)
# The audit trail is the identity of whoever acted, not business data, so it is
# the one router with a narrower rule.
app.include_router(audit.router, dependencies=[Depends(authorize(ApiAction.AUDIT_READ))])
app.include_router(monitoring.router, dependencies=BUSINESS)
app.include_router(research.router, dependencies=BUSINESS)
app.include_router(products.router, dependencies=BUSINESS)
app.include_router(sourcing.router, dependencies=BUSINESS)
app.include_router(economics.router, dependencies=BUSINESS)
app.include_router(legal.router, dependencies=BUSINESS)
app.include_router(ecommerce.router, dependencies=BUSINESS)
app.include_router(marketplace.router, dependencies=BUSINESS)
app.include_router(marketing.router, dependencies=BUSINESS)
app.include_router(operations.router, dependencies=BUSINESS)
app.include_router(cfo.router, dependencies=BUSINESS)
app.include_router(pipeline.router, dependencies=BUSINESS)
app.include_router(incidents.router, dependencies=BUSINESS)
app.include_router(jobs.router, dependencies=BUSINESS)
