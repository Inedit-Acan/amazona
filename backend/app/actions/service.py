"""El ciclo de vida de una acción con efecto fuera del sistema (hardening pre-M44, ADR 0024).

    open ─▶ PENDING ─reserve─▶ begin_call (commit) ─▶ CALLING ─adapter─▶ SUCCEEDED
                                                                  ├────▶ FAILED_CONFIRMED
                                                                  └────▶ UNKNOWN_OUTCOME

Cada flecha entre estados es un **compare-and-set** (`UPDATE ... WHERE status = :esperado`): dos ejecutores,
o un barredor y un reintento, no pueden ganar los dos. Y hay **una** frontera de durabilidad, `begin_call`: lo
que existe en la base antes de que la petición salga hacia el proveedor. Si el proceso muere antes del commit
de `begin_call`, nada salió y se puede liberar la reserva; si muere después, no se sabe qué hizo el proveedor y
**no se libera nada**.
"""

import datetime
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.actions.contract import (
    OPEN_STATUSES,
    ActionRequest,
    ActionResponse,
    ActionStatus,
    ExternalActionAdapter,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnreachableError,
    derive_idempotency_key,
    request_fingerprint,
)
from app.budgets.service import BudgetLedgerService
from app.core.errors import (
    AmazonaError,
    ExternalActionFailedError,
    ExternalOutcomeUnknownError,
    PipelineDisabledError,
    ValidationError,
)
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.pipeline.kill_switch import PipelineKillSwitchService

ACTION_ACTOR = "external-actions"
_OPEN_VALUES = tuple(status.value for status in OPEN_STATUSES)


class ExternalActionStateError(AmazonaError):
    """The action is not in the state this operation needs (someone else moved it first)."""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class ExternalActionService:
    def __init__(
        self,
        db: Session,
        *,
        ledger: BudgetLedgerService | None = None,
        kill_switch: PipelineKillSwitchService | None = None,
        clock: Callable[[], datetime.datetime] = _utcnow,
    ) -> None:
        self._db = db
        self._ledger = ledger or BudgetLedgerService(db)
        self._kill_switch = kill_switch or PipelineKillSwitchService(db)
        self._clock = clock

    # --- Abrir -------------------------------------------------------------------------

    def open(
        self,
        *,
        reference: str,
        adapter: ExternalActionAdapter,
        operation: str,
        amount: float | None,
        payload: dict,
        correlation_id: str,
    ) -> ExternalAction:
        """La operación de este «sitio»: la que ya está abierta (un reintento de la misma) o una nueva.

        Se reutiliza la operación —y con ella la clave hacia el proveedor y la reserva— mientras no esté
        cerrada: abierta (`PENDING`, `CALLING`, `UNKNOWN_OUTCOME`) o con el efecto ya hecho pero sin registrar
        localmente (`SUCCEEDED` sin `applied_at`). Solo cuando se cierra del todo, o falla confirmado, una nueva
        operación (otra `sequence`, otra clave) puede abrirse. Rehacer un paso a propósito es una operación nueva;
        reintentarlo, no."""
        self._serialise(f"external-action:{reference}")
        fingerprint = request_fingerprint(adapter.name, operation, amount, payload)
        latest = self._latest(reference)
        if latest is not None and self._still_owns_the_site(latest):
            if latest.request_fingerprint != fingerprint:
                raise ValidationError(
                    f"{reference} already has an unfinished {latest.operation} with a different request: "
                    "finish or resolve it before asking for another"
                )
            return latest

        sequence = (latest.sequence if latest is not None else 0) + 1
        action = ExternalAction(
            reference=reference,
            sequence=sequence,
            provider=adapter.name,
            operation=operation,
            idempotency_key=derive_idempotency_key(reference, sequence),
            provider_idempotent=bool(adapter.supports_idempotency),
            request_fingerprint=fingerprint,
            amount=amount,
            status=ActionStatus.PENDING.value,
            correlation_id=correlation_id,
        )
        self._db.add(action)
        self._db.flush()
        self._audit(
            action,
            "open",
            before=None,
            after={"sequence": sequence, "provider": adapter.name, "provider_idempotent": action.provider_idempotent},
        )
        return action

    def reserve(self, action: ExternalAction) -> bool:
        """Reserva el importe de la operación en el libro, una sola vez por operación (`action:{id}`). Una
        acción que no gasta, o sin presupuesto autorizado en una simulación declarada, no tiene nada que
        reservar."""
        if not action.amount or float(action.amount) <= 0:
            return True
        if self._ledger.find_budget() is None:
            return True
        return self._ledger.reserve(
            amount=float(action.amount), reference=action.reservation_reference, idempotent=True
        )

    # --- Llamar ------------------------------------------------------------------------

    def begin_call(self, action: ExternalAction) -> None:
        """`PENDING -> CALLING` y **commit**: lo que queda en la base antes de que la petición salga.

        El kill switch se vuelve a mirar aquí, justo antes del efecto irreversible: si se apagó entre que se
        autorizó y que se va a ejecutar, no sale nada."""
        if action.status != ActionStatus.PENDING.value:
            raise ExternalActionStateError(f"action {action.id} is {action.status}, not PENDING")
        if not self._kill_switch.is_enabled():
            raise PipelineDisabledError("the kill switch was turned off before the external call was sent")
        if not self._transition(
            action,
            {ActionStatus.PENDING},
            ActionStatus.CALLING,
            call_started_at=self._clock(),
            updated_at=self._clock(),
        ):
            raise ExternalActionStateError(f"action {action.id} was moved by someone else before the call")
        self._audit(action, "call_started", before={"status": "PENDING"}, after={"status": "CALLING"})
        self._db.commit()

    def execute(self, action: ExternalAction, adapter: ExternalActionAdapter, payload: dict) -> ActionResponse:
        """Ejecuta la operación y deja constancia del resultado, sea cual sea.

        - éxito confirmado: `SUCCEEDED` y la reserva se compromete;
        - rechazo o petición que no salió: `FAILED_CONFIRMED` y la reserva se libera;
        - timeout, o cualquier otra cosa que no diga «no hubo efecto»: `UNKNOWN_OUTCOME`, la reserva **se queda**.

        Lanza `ExternalActionFailedError` o `ExternalOutcomeUnknownError`; nunca declara éxito ni fallo seguro
        cuando no se sabe."""
        if action.status == ActionStatus.SUCCEEDED.value:
            return ActionResponse(reference=None, detail={"already_done": True})
        self.begin_call(action)
        request = ActionRequest(
            provider=action.provider,
            operation=action.operation,
            idempotency_key=action.idempotency_key if adapter.supports_idempotency else None,
            amount=float(action.amount) if action.amount is not None else None,
            payload=payload,
            correlation_id=action.correlation_id,
        )
        try:
            response = adapter.execute(request)
        except (ProviderRejectedError, ProviderUnreachableError) as exc:
            self.finish(action, ActionStatus.FAILED_CONFIRMED, error=f"{type(exc).__name__}: {exc}")
            raise ExternalActionFailedError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - un fallo que no diga «no hubo efecto» es desconocido
            self.finish(action, ActionStatus.UNKNOWN_OUTCOME, error=f"{type(exc).__name__}: {exc}")
            raise ExternalOutcomeUnknownError(
                f"the outcome of {action.operation} on {action.provider} is unknown ({type(exc).__name__}): "
                "it may have been executed"
            ) from exc
        self.finish(action, ActionStatus.SUCCEEDED)
        return response

    def finish(self, action: ExternalAction, status: ActionStatus, *, error: str | None = None) -> None:
        """Cierra una operación que estaba `CALLING` y mueve el libro como corresponde: `SUCCEEDED` compromete,
        `FAILED_CONFIRMED` libera, `UNKNOWN_OUTCOME` no toca nada (la reserva se queda hasta que se sepa). Salir
        de `UNKNOWN_OUTCOME` solo se hace por `reconcile` o `resolve`."""
        now = self._clock()
        fields: dict = {"finished_at": now, "updated_at": now, "error": (error or "")[:2000] or None}
        if status is ActionStatus.UNKNOWN_OUTCOME:
            fields["finished_at"] = None
        if not self._transition(action, {ActionStatus.CALLING}, status, **fields):
            raise ExternalActionStateError(f"action {action.id} was already closed by someone else")
        if status is ActionStatus.SUCCEEDED:
            self._move_ledger(action, commit=True)
        elif status is ActionStatus.FAILED_CONFIRMED:
            self._move_ledger(action, commit=False)
        self._audit(action, status.value.lower(), before=None, after={"status": status.value, "error": error})
        self._db.commit()

    def mark_applied(self, action: ExternalAction) -> None:
        """El paso registró localmente este resultado: a partir de aquí la operación está del todo cerrada."""
        action.applied_at = self._clock()

    # --- Tras una caída ----------------------------------------------------------------

    def latest(self, reference: str) -> ExternalAction | None:
        return self._latest(reference)

    def mark_interrupted(self, reference: str) -> ExternalAction | None:
        """Si el intento anterior de este sitio cayó **después** de empezar la llamada (`CALLING`), no se sabe qué
        hizo el proveedor: pasa a `UNKNOWN_OUTCOME`, y la reserva se queda. Devuelve la operación si quedó (o ya
        estaba) en ese estado."""
        latest = self._latest(reference)
        if latest is None:
            return None
        if latest.status == ActionStatus.CALLING.value:
            self._transition(
                latest,
                {ActionStatus.CALLING},
                ActionStatus.UNKNOWN_OUTCOME,
                error="the attempt that was calling the provider did not finish",
                updated_at=self._clock(),
            )
            self._audit(latest, "unknown_outcome", before={"status": "CALLING"}, after={"status": "UNKNOWN_OUTCOME"})
            self._db.commit()
        return latest if latest.status == ActionStatus.UNKNOWN_OUTCOME.value else None

    def reconcile_interrupted(self, *, older_than: datetime.timedelta) -> dict[str, list[str]]:
        """El barrido de operaciones huérfanas. Distingue por **qué lado de la frontera** quedaron:

        - `PENDING` desde hace más de `older_than`: la petición nunca salió → se libera la reserva y se cierra
          como `FAILED_CONFIRMED` (no se ejecutó nada);
        - `CALLING` desde hace más de `older_than`: no se sabe → `UNKNOWN_OUTCOME`, **la reserva se queda**.

        `older_than` tiene que ser mayor que el arriendo del trabajo: es la prueba de que su ejecutor ya no está.
        Las transiciones son compare-and-set, así que un ejecutor que justo despierte y un barrido no pueden
        ganar los dos."""
        limit = self._clock() - older_than
        released: list[str] = []
        unknown: list[str] = []
        stale = (
            self._db.query(ExternalAction)
            .filter(ExternalAction.status.in_(["PENDING", "CALLING"]), ExternalAction.updated_at < limit)
            .order_by(ExternalAction.created_at)
            .all()
        )
        for action in stale:
            if action.status == ActionStatus.PENDING.value:
                try:
                    self.finish_unstarted(action)
                    released.append(action.id)
                except ExternalActionStateError:
                    continue
            else:
                if self._transition(
                    action,
                    {ActionStatus.CALLING},
                    ActionStatus.UNKNOWN_OUTCOME,
                    error="the attempt that was calling the provider did not finish",
                    updated_at=self._clock(),
                ):
                    self._audit(
                        action, "unknown_outcome", before={"status": "CALLING"}, after={"status": "UNKNOWN_OUTCOME"}
                    )
                    unknown.append(action.id)
        self._db.commit()
        return {"released": released, "unknown": unknown}

    def finish_unstarted(self, action: ExternalAction) -> None:
        """La petición no llegó a salir: no hubo efecto. Cierra la operación y libera la reserva."""
        now = self._clock()
        if not self._transition(
            action,
            {ActionStatus.PENDING},
            ActionStatus.FAILED_CONFIRMED,
            error="the request was never sent (reconciled)",
            finished_at=now,
            updated_at=now,
            resolved_by="reconciler",
            resolved_at=now,
        ):
            raise ExternalActionStateError(f"action {action.id} started before it could be released")
        self._move_ledger(action, commit=False)
        self._audit(action, "release_unstarted", before={"status": "PENDING"}, after={"status": "FAILED_CONFIRMED"})
        self._db.commit()

    # --- Resolver un resultado desconocido --------------------------------------------

    def reconcile(self, action: ExternalAction, adapter: ExternalActionAdapter, payload: dict) -> ActionStatus:
        """Intenta saber qué pasó, **sin** inventarlo:

        1. si el adaptador sabe consultarlo (`lookup`), se le pregunta por la clave de la operación;
        2. si no, pero declara idempotencia, se **repite la misma petición con la misma clave**: el proveedor se
           compromete a no repetir el efecto, así que su respuesta es la de la operación original;
        3. si no puede ninguna de las dos (sin idempotencia ni consulta), se queda en `UNKNOWN_OUTCOME` y hace falta
           una persona.

        Un timeout al reconciliar tampoco resuelve nada: sigue desconocido."""
        if action.status != ActionStatus.UNKNOWN_OUTCOME.value:
            return ActionStatus(action.status)
        lookup = getattr(adapter, "lookup", None)
        try:
            if callable(lookup):
                found = lookup(action.idempotency_key)
                self._close_unknown(
                    action,
                    ActionStatus.SUCCEEDED if found is not None else ActionStatus.FAILED_CONFIRMED,
                    "reconciler:lookup",
                    "the provider confirmed the operation"
                    if found is not None
                    else "the provider has no such operation",
                )
            elif adapter.supports_idempotency:
                request = ActionRequest(
                    provider=action.provider,
                    operation=action.operation,
                    idempotency_key=action.idempotency_key,
                    amount=float(action.amount) if action.amount is not None else None,
                    payload=payload,
                    correlation_id=action.correlation_id,
                )
                adapter.execute(request)
                self._close_unknown(
                    action, ActionStatus.SUCCEEDED, "reconciler:key-replay", "replayed with the same key"
                )
            else:
                return ActionStatus.UNKNOWN_OUTCOME
        except (ProviderRejectedError, ProviderUnreachableError, ProviderTimeoutError):
            # Repetir la clave y no obtener respuesta, o que la rechacen, no prueba que el original no se
            # ejecutara: solo una consulta del proveedor o una persona pueden afirmarlo.
            return ActionStatus.UNKNOWN_OUTCOME
        return ActionStatus(action.status)

    def resolve(self, action: ExternalAction, *, succeeded: bool, actor: str, reason: str) -> None:
        """Una persona cierra un resultado desconocido tras comprobarlo por su cuenta: `succeeded` compromete la
        reserva, lo contrario la libera. Queda quién, cuándo y por qué."""
        if not reason.strip():
            raise ValidationError("resolving an unknown outcome needs a reason")
        self._close_unknown(
            action, ActionStatus.SUCCEEDED if succeeded else ActionStatus.FAILED_CONFIRMED, actor, reason
        )

    def _close_unknown(self, action: ExternalAction, status: ActionStatus, by: str, why: str) -> None:
        now = self._clock()
        if not self._transition(
            action,
            {ActionStatus.UNKNOWN_OUTCOME},
            status,
            finished_at=now,
            updated_at=now,
            resolved_by=by,
            resolved_at=now,
            error=why[:2000],
        ):
            raise ExternalActionStateError(f"action {action.id} is no longer UNKNOWN_OUTCOME")
        self._move_ledger(action, commit=status is ActionStatus.SUCCEEDED)
        self._audit(
            action,
            "resolve",
            before={"status": "UNKNOWN_OUTCOME"},
            after={"status": status.value, "by": by, "why": why},
            actor=by,
        )
        self._db.commit()

    # --- Interno -----------------------------------------------------------------------

    def _latest(self, reference: str) -> ExternalAction | None:
        return (
            self._db.query(ExternalAction)
            .filter_by(reference=reference)
            .order_by(ExternalAction.sequence.desc())
            .first()
        )

    @staticmethod
    def _still_owns_the_site(action: ExternalAction) -> bool:
        return action.status in _OPEN_VALUES or (
            action.status == ActionStatus.SUCCEEDED.value and action.applied_at is None
        )

    def _transition(self, action: ExternalAction, expected: set[ActionStatus], to: ActionStatus, **fields) -> bool:
        """`UPDATE ... SET status = :to WHERE id = :id AND status IN :expected`: True solo para quien cambia la fila."""
        result = self._db.execute(
            update(ExternalAction)
            .where(ExternalAction.id == action.id, ExternalAction.status.in_([s.value for s in expected]))
            .values(status=to.value, **fields)
            .execution_options(synchronize_session=False)
        )
        assert isinstance(result, CursorResult)
        moved = result.rowcount == 1
        self._db.refresh(action)
        return moved

    def _move_ledger(self, action: ExternalAction, *, commit: bool) -> None:
        """Compromete o libera **lo que esta operación tiene reservado**, y nada más: sin reserva viva (una
        simulación sin presupuesto, o un movimiento que ya se hizo) no hay nada que mover, y liberar a ciegas
        restaría de la reserva de otra operación."""
        if not action.amount or Decimal(str(action.amount)) <= 0:
            return
        reference = action.reservation_reference
        amount = float(self._ledger.outstanding(reference))
        if amount <= 0:
            return
        if commit:
            self._ledger.record_commit(amount=amount, reference=reference)
        else:
            self._ledger.record_release(amount=amount, reference=reference)

    def _audit(
        self,
        action: ExternalAction,
        event: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        actor: str = ACTION_ACTOR,
    ) -> None:
        self._db.add(
            AuditLog(
                actor=actor,
                action=f"external_action.{event}",
                resource=f"external_action:{action.id}",
                before=before,
                after={**(after or {}), "reference": action.reference, "operation": action.operation},
                correlation_id=action.correlation_id,
            )
        )

    def _serialise(self, key: str) -> None:
        if self._db.get_bind().dialect.name == "postgresql":
            self._db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
