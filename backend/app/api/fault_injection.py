"""Armar un fallo de ENSAYO en una tarea (M51A). Infraestructura de QA, no una función del producto.

La ÚNICA operación es armar. No hay forma de desarmar, listar ni armar en bloque: el armado vive en
la memoria del proceso, se consume
al dispararse y caduca (`app.fault_injection`). La ruta solo existe si
`Settings.fault_injection_allowed` (activada en un `development`
con todos los proveedores simulados): en cualquier otro caso responde 404 a todo el mundo, ANTES de
mirar quién pregunta. No sale en el
esquema público (`/docs`, `openapi.json`). Armar exige OWNER/ADMIN (`ApiAction.FAULT_INJECT`) y una
`Idempotency-Key` aunque sea una
simulación, y queda en `fault.armed`.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.objective import Objective as ObjectiveModel
from app.db.session import get_db
from app.fault_injection import MAX_ATTEMPT, OBJECTIVE_ID_PATTERN, drain_expired_audit, get_fault_injector
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.permissions.policies import ApiAction, role_can


def require_fault_injection(settings: Settings = Depends(get_settings)) -> None:
    """Apagada, o en un entorno que no la permite: la ruta NO EXISTE (404), sin mirar quién pregunta."""
    if not settings.fault_injection_allowed:
        raise NotFoundError("not found")


def authorize_fault_injection(actor: Actor = Depends(authorize(ApiAction.FAULT_INJECT))) -> Actor:
    """Solo una identidad VERIFICADA con rol OWNER o ADMIN. La ruta solo existe en `development`,
    donde `authorize` NO hace cumplir
    los roles (eso es de staging y production): aquí sí, siempre. Sin token (el actor local sin
    autenticar) es un 401: para armar un
    fallo el backend del ensayo tiene que arrancar con `REQUIRE_AUTH=true` y un usuario OWNER/ADMIN."""
    if not actor.is_verified:
        raise HTTPException(status_code=401, detail="arming a fault requires a verified OWNER or ADMIN identity")
    if not role_can(actor.role, ApiAction.FAULT_INJECT):
        raise HTTPException(status_code=403, detail=f"role {actor.role or 'none'} is not allowed to arm a fault")
    return actor


router = APIRouter(
    prefix="/api/test-support/faults",
    tags=["test-support"],
    include_in_schema=False,
    dependencies=[Depends(require_fault_injection)],
)


class ArmIn(BaseModel):
    """Exactamente `(objective_id, task_name, attempt)`: sin comodines, sin patrones, sin más campos."""

    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(pattern=f"^{OBJECTIVE_ID_PATTERN}$")
    task_name: str = Field(min_length=1, max_length=64)
    attempt: int = Field(ge=1, le=MAX_ATTEMPT, strict=True)


class ArmedOut(BaseModel):
    objective_id: str
    task_name: str
    attempt: int
    armed_by: str
    armed_at: str
    expires_at: str
    #: La correlación de `fault.armed` (y de `fault.expired`, si caduca).
    correlation_id: str


@router.post("", response_model=ArmedOut)
def arm_fault(
    payload: ArmIn,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize_fault_injection),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ArmedOut:
    """Arma UN fallo para la tarea `task_name` del objetivo, en el intento `attempt`: se dispara
    una sola vez y caduca a los 30
    minutos. El objetivo tiene que existir. Con `Idempotency-Key` (obligatoria), repetir la
    petición devuelve lo mismo sin armar
    otra vez. 409 si ya hay un fallo armado."""

    def work() -> ArmedOut:
        if db.get(ObjectiveModel, payload.objective_id) is None:
            raise NotFoundError(f"objective {payload.objective_id} not found")
        drain_expired_audit(db)
        correlation_id = new_correlation_id()
        injector = get_fault_injector()
        fault = injector.arm(
            objective_id=payload.objective_id,
            task_name=payload.task_name,
            attempt=payload.attempt,
            armed_by=identity.subject,
            correlation_id=correlation_id,
        )
        try:
            db.add(
                AuditLog(
                    actor=identity.subject,
                    action="fault.armed",
                    resource=f"objective:{fault.objective_id}",
                    before=None,
                    after={**fault.audit_after(), "actor": identity.subject},
                    correlation_id=correlation_id,
                )
            )
            db.commit()
        except Exception:
            injector.disarm(fault)  # sin auditoría confirmada no queda nada armado
            raise
        return ArmedOut(
            objective_id=fault.objective_id,
            task_name=fault.task_name,
            attempt=fault.attempt,
            armed_by=fault.armed_by,
            armed_at=fault.armed_at.isoformat(),
            expires_at=fault.expires_at.isoformat(),
            correlation_id=correlation_id,
        )

    return run_idempotent(
        db,
        scope="faults.arm",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload=payload.model_dump(),
        response=response,
        status_code=200,
        response_model=ArmedOut,
        work=work,
        always_required=True,
    )
