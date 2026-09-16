from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import agents, approvals, audit, decisions, objectives, projects, tasks
from app.approvals.service import ApprovalNotPendingError
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.core.logging import configure_logging, set_correlation_id

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


app.include_router(objectives.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(agents.router)
app.include_router(decisions.router)
app.include_router(approvals.router)
app.include_router(audit.router)
