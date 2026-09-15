from fastapi import FastAPI, Request

from app.core.config import get_settings
from app.core.ids import new_correlation_id
from app.core.logging import configure_logging, set_correlation_id

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="AMAZONA Backend")

CORRELATION_ID_HEADER = "X-Correlation-ID"


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
