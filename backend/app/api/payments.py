"""El webhook de un proveedor de pagos (Milestone 44, ADR 0028 §1).

**No usa el token de nadie**: quien llama es el proveedor, y se autentica por la firma del cuerpo bruto. Por eso este
router se incluye sin las dependencias de lectura de negocio.

- El cuerpo se lee en bruto y se pasa a `PaymentIngress`, que lo verifica **antes** de escribir nada y lo descarta:
  solo se guarda su hash y una lista blanca de campos.
- Una verificación fallida es un 400 con un mensaje fijo: no se cuenta qué comprobación falló.
- Un proveedor que no está habilitado en este entorno es un 404. El simulador, además, firma con una clave efímera de
  su proceso: desde fuera nadie puede firmarle un evento.
- El mismo evento otra vez es un 200 sin efecto; con otro contenido bajo el mismo id, un 409.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.payments.ingress import MAX_WEBHOOK_BODY_BYTES, PaymentIngress
from app.payments.port import WebhookVerificationError

router = APIRouter(prefix="/api/payments", tags=["payments"])


class WebhookAck(BaseModel):
    #: `applied`, `stale`, `conflict` o `unmatched`. Se contesta 200 en todos para que el proveedor deje de reintentar:
    #: la evidencia ya está guardada.
    status: str
    duplicate: bool


@router.post("/webhooks/{provider}", response_model=WebhookAck)
async def receive_webhook(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "webhook body too large"})
    raw_body = await request.body()
    headers = dict(request.headers)

    def process():
        return PaymentIngress(db, settings=settings).receive(provider, headers, raw_body)

    try:
        result = await run_in_threadpool(process)
    except WebhookVerificationError:
        return JSONResponse(status_code=400, content={"detail": "invalid webhook"})
    return WebhookAck(status=result.outcome, duplicate=result.duplicate)
