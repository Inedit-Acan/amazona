"""Comprar, enviar y cerrar un fulfillment (Milestone 44, ADR 0028 §6).

Comprar y enviar son **acciones externas gobernadas**: pasan por el ActionGate y por `ExternalAction`, con
`Idempotency-Key` obligatoria siempre. Confirmar la entrega, cancelar y abandonar son transiciones de estado con
compare-and-set: repetirlas es un 409. Ninguna ruta acepta un estado: el cliente pide una operación, y lo que
pasó fuera lo cuenta el observador de la acción.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.orders import FulfilmentOut, fulfillment_out
from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.orders.fulfilment import FulfilmentService
from app.orders.payment_attempts import Requester
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/fulfillments", tags=["fulfillments"])


def _requester(identity: Actor) -> Requester:
    return Requester(name=identity.audit_name, role=identity.role.value if identity.role else None)


def _external(
    phase: str,
    fulfillment_id: str,
    response: Response,
    db: Session,
    identity: Actor,
    settings: Settings,
    idempotency_key: str | None,
) -> FulfilmentOut:
    def work() -> FulfilmentOut:
        service = FulfilmentService(db, settings=settings)
        done = (
            service.purchase(fulfillment_id, requester=_requester(identity))
            if phase == "purchase"
            else service.ship(fulfillment_id, requester=_requester(identity))
        )
        return fulfillment_out(db, done)

    return run_idempotent(
        db,
        scope=f"fulfillments.{phase}",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"fulfillment_id": fulfillment_id},
        response=response,
        status_code=200,
        response_model=FulfilmentOut,
        work=work,
        always_required=True,
    )


@router.post("/{fulfillment_id}/purchase", response_model=FulfilmentOut)
def purchase(
    fulfillment_id: str,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> FulfilmentOut:
    """Compra al proveedor lo que cubre el fulfillment. Resultado: `PURCHASED`, `READY` (el proveedor confirmó que no
    compró; se puede reintentar con otra clave) o `UNKNOWN_OUTCOME` (pudo comprar; **bloquea** nuevos intentos y no
    devuelve unidades al pool hasta reconciliarlo o resolverlo). La misma clave devuelve la misma respuesta."""
    return _external("purchase", fulfillment_id, response, db, identity, settings, idempotency_key)


@router.post("/{fulfillment_id}/ship", response_model=FulfilmentOut)
def ship(
    fulfillment_id: str,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> FulfilmentOut:
    """Manda el envío de lo comprado. Resultado: `SHIPPED`, `PURCHASED` (confirmado que no se envió: sigue comprado,
    asignado y a la vista de alguien) o `UNKNOWN_OUTCOME`."""
    return _external("ship", fulfillment_id, response, db, identity, settings, idempotency_key)


@router.post("/{fulfillment_id}/complete", response_model=FulfilmentOut)
def complete(
    fulfillment_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
) -> FulfilmentOut:
    """Confirma la entrega de un envío (una persona, con actor: aún no hay transportistas). Con ella, si todas las
    unidades del pedido están entregadas, el pedido pasa a `COMPLETED`."""
    return fulfillment_out(db, FulfilmentService(db).complete(fulfillment_id, actor=identity.audit_name))


@router.post("/{fulfillment_id}/cancel", response_model=FulfilmentOut)
def cancel(
    fulfillment_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
) -> FulfilmentOut:
    """Cancela un fulfillment que **nunca compró** y devuelve sus unidades al pool. Uno que ya compró, que pudo
    comprar o cuyo resultado se desconoce no puede cancelarse: sus unidades no vuelven (evita comprar dos veces)."""
    return fulfillment_out(db, FulfilmentService(db).cancel(fulfillment_id, actor=identity.audit_name))


@router.post("/{fulfillment_id}/fail", response_model=FulfilmentOut)
def fail(
    fulfillment_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
) -> FulfilmentOut:
    """Abandona un fulfillment cuya compra falló de forma confirmada y nunca compró; devuelve sus unidades."""
    return fulfillment_out(db, FulfilmentService(db).fail(fulfillment_id, actor=identity.audit_name))
