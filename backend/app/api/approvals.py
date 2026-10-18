import datetime
from collections.abc import Iterable
from typing import Literal, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.approvals.service import ApprovalNotPendingError
from app.auth.actor import Actor
from app.auth.dependencies import actor_name, authorize
from app.budgets.service import BudgetLedgerService
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.db.models.approval import Approval as ApprovalModel
from app.db.models.audit import AuditLog as AuditLogModel
from app.db.models.budget import FinancialEvent
from app.db.session import get_db
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    decision_id: str
    action: str
    amount: float | None
    status: str
    expires_at: datetime.datetime | None
    resolved_at: datetime.datetime | None
    resolved_by: str | None
    # Commit 6a: existían en la tabla (ambos NOT NULL) y no salían. `requested_at` es cuándo se PIDIÓ la aprobación (ni
    # su caducidad ni su resolución); `correlation_id` es el de la ejecución del CEO que la pidió: el mismo de su
    # decisión, de su auditoría y de su log de ejecuciones.
    requested_at: datetime.datetime
    correlation_id: str
    # Corrección tras la primera misión real: lo que esta aprobación hizo en el LIBRO del presupuesto
    # (`financial_events`, por la referencia `approval:<id>`), no lo que se supone por tener un importe.
    # `none`: ningún movimiento (sin presupuesto autorizado en un despliegue simulado, importe cero o
    # desconocido…); `reserved`: reservado y sin liquidar; `committed` / `released`: ya liquidado.
    budget_effect: Literal["none", "reserved", "committed", "released"] = "none"

    @field_validator("requested_at")
    @classmethod
    def _requested_at_with_zone(cls, value: datetime.datetime) -> datetime.datetime:
        """SQLite descarta la zona al leer y todo lo que se guarda aquí es UTC: el campo nuevo sale SIEMPRE con zona,
        para que un cliente no lo lea como hora local. (Los campos antiguos no cambian.)"""
        return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


class ApprovalActionIn(BaseModel):
    # OPCIONAL: sin él el actor es el de la identidad (el verificado con token; `local-development` sin
    # autenticar). Un nombre declarado solo se acepta fuera de staging y production (`actor_name`) y se
    # guarda como `declared`.
    actor: str | None = None


def _effects_from_events(events: Iterable[tuple[str | None, str]]) -> dict[str, str]:
    """El efecto de cada aprobación en el libro: `approval_id` → `committed` | `released` | `reserved`.

    Las que no tienen ningún movimiento no aparecen (su efecto es `none`). Una referencia se reserva una vez y se
    liquida una vez (ADR 0026). `financial_events.reference` admite NULL: un movimiento sin referencia no pertenece
    a ninguna aprobación y se ignora de forma explícita."""
    kinds: dict[str, set[str]] = {}
    for reference, kind in events:
        if reference is None:
            continue
        kinds.setdefault(reference.removeprefix("approval:"), set()).add(kind)
    effects: dict[str, str] = {}
    for approval_id, seen in kinds.items():
        if "COMMIT" in seen:
            effects[approval_id] = "committed"
        elif "RELEASE" in seen:
            effects[approval_id] = "released"
        elif "RESERVE" in seen:
            effects[approval_id] = "reserved"
    return effects


def _budget_effects(db: Session) -> dict[str, str]:
    query = db.query(FinancialEvent.reference, FinancialEvent.type)
    rows = query.filter(FinancialEvent.reference.like("approval:%")).all()
    return _effects_from_events((reference, kind) for reference, kind in rows)


def _settle_reservation(ledger: BudgetLedgerService, approval: ApprovalModel, *, commit: bool) -> None:
    """Compromete o libera lo que ESTA aprobación tiene reservado en el libro, y nada más.

    Sin reserva viva (se pidió sin presupuesto autorizado en un despliegue simulado, o su importe es 0) no hay
    movimiento financiero: la aprobación se resuelve igual (`PENDING → APPROVED | REJECTED | EXPIRED`) y el libro no se
    toca. Liquidar a ciegas habría comprometido dinero que nadie reservó o liberado la reserva de OTRA aprobación."""
    reference = f"approval:{approval.id}"
    live = ledger.outstanding(reference)
    if live <= 0:
        return
    if commit:
        ledger.record_commit(amount=float(live), reference=reference)
    else:
        ledger.record_release(amount=float(live), reference=reference)


def _out(approval: ApprovalModel, effects: dict[str, str]) -> ApprovalOut:
    out = ApprovalOut.model_validate(approval)
    return out.model_copy(update={"budget_effect": effects.get(approval.id, "none")})


@router.get("", response_model=list[ApprovalOut])
def list_approvals(db: Session = Depends(get_db)) -> list[ApprovalOut]:
    effects = _budget_effects(db)
    return [_out(approval, effects) for approval in db.query(ApprovalModel).all()]


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
def approve_approval(
    approval_id: str,
    payload: ApprovalActionIn,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.APPROVAL_RESOLVE)),
    settings: Settings = Depends(get_settings),
) -> ApprovalOut:
    approval = _resolve(approval_id, "APPROVED", db, identity, payload.actor, settings)
    return _out(approval, _budget_effects(db))


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
def reject_approval(
    approval_id: str,
    payload: ApprovalActionIn,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.APPROVAL_RESOLVE)),
    settings: Settings = Depends(get_settings),
) -> ApprovalOut:
    approval = _resolve(approval_id, "REJECTED", db, identity, payload.actor, settings)
    return _out(approval, _budget_effects(db))


def _as_aware_utc(value: datetime.datetime) -> datetime.datetime:
    """SQLite drops tzinfo on round-trip; every stored datetime here is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)


def _claim(db: Session, approval_id: str, *, to_status: str, now: datetime.datetime, resolved_by: str | None) -> bool:
    """Compare-and-set: `PENDING` -> `to_status`, en **una sola sentencia**.

    Devuelve True solo para la petición que ha cambiado la fila. Leer el estado,
    comprobar en Python que sigue `PENDING` y escribir después dejaba que N peticiones
    simultáneas vieran todas `PENDING` y todas registraran su `record_commit`: el
    `UPDATE ... WHERE status = 'PENDING'` hace que, de N, solo una afecte a una fila y
    las demás (que esperan a que la primera confirme y vuelven a evaluar el WHERE)
    afecten a cero.
    """
    result = cast(
        CursorResult,
        db.execute(
            update(ApprovalModel)
            .where(ApprovalModel.id == approval_id, ApprovalModel.status == "PENDING")
            .values(status=to_status, resolved_at=now, resolved_by=resolved_by)
            .execution_options(synchronize_session=False)
        ),
    )
    return result.rowcount == 1


def _not_pending(db: Session, approval: ApprovalModel) -> ApprovalNotPendingError:
    """La respuesta de siempre para «ya resuelta», con el estado que tiene ahora
    de verdad en la base (no el que se leyó al principio)."""
    db.refresh(approval)
    return ApprovalNotPendingError(f"approval {approval.id} is not pending (status={approval.status})")


def _resolve(
    approval_id: str,
    new_status: str,
    db: Session,
    identity: Actor,
    declared: str | None,
    settings: Settings,
) -> ApprovalModel:
    actor = actor_name(identity, declared, settings)
    approval = db.get(ApprovalModel, approval_id)
    if approval is None:
        raise NotFoundError(f"approval {approval_id} not found")

    now = datetime.datetime.now(datetime.UTC)
    budget_ledger = BudgetLedgerService(db)
    if approval.status == "PENDING" and approval.expires_at and _as_aware_utc(approval.expires_at) <= now:
        # Caducar es también una resolución: solo una petición la hace, y solo ella
        # libera la reserva. Si otra ya resolvió, esa es la que manda.
        if _claim(db, approval_id, to_status="EXPIRED", now=now, resolved_by=None):
            _settle_reservation(budget_ledger, approval, commit=False)
            db.add(
                AuditLogModel(
                    actor="system",
                    action="approval.expire",
                    resource=f"approval:{approval.id}",
                    before={"status": "PENDING"},
                    after={"status": "EXPIRED"},
                    correlation_id=approval.correlation_id,
                )
            )
            db.commit()
        else:
            db.rollback()
        raise _not_pending(db, approval)

    if approval.status != "PENDING":
        raise _not_pending(db, approval)

    if not _claim(db, approval_id, to_status=new_status, now=now, resolved_by=actor):
        db.rollback()
        raise _not_pending(db, approval)

    before_status = "PENDING"
    _settle_reservation(budget_ledger, approval, commit=new_status == "APPROVED")
    action_verb = "approve" if new_status == "APPROVED" else "reject"
    db.add(
        AuditLogModel(
            actor=actor,
            actor_role=identity.role,
            actor_source=identity.source,
            action=f"approval.{action_verb}",
            resource=f"approval:{approval.id}",
            before={"status": before_status},
            after={"status": new_status},
            correlation_id=approval.correlation_id,
        )
    )
    db.commit()
    db.refresh(approval)
    return approval
