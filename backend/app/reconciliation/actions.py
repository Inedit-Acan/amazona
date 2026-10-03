"""El barrido programado de acciones externas abandonadas (Milestone 45, ADR 0029 §1, §3 y §5).

Lo que hace, y **solo** esto:

- una acción `PENDING` más vieja que el umbral (la petición **nunca salió**: la frontera de durabilidad `begin_call`
lo prueba) se cierra
  `FAILED_CONFIRMED` y libera su reserva;
- una acción `CALLING` más vieja que el umbral (medida desde que **empezó la llamada**) pasa a `UNKNOWN_OUTCOME` y
**conserva su reserva**.
  Superar el umbral **nunca** es un `FAILED_CONFIRMED`: pudo salir.

Lo que **no** hace: no toca un `UNKNOWN_OUTCOME` (solo lo cierra la respuesta tardía, una consulta autoritativa o una
persona), no llama a
`execute`, no repite ninguna petición y no llama a `reconcile()`. Es lo que lo hace seguro aunque el umbral se quede
corto: un ejecutor vivo al
que se le adelantan pierde el compare-and-set (un 409 sin enviar nada) o su respuesta tardía cierra la operación.

**Una transacción por elemento.** `ExternalActionService.sweep_one` confirma cada operación por separado; un fallo en
una (un observador que
lanza, la base que se cae un instante) se registra y **no aborta el lote**. Los `BaseException` (una caída del
proceso) no se tragan.
"""

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog

logger = logging.getLogger(__name__)

RECONCILER_ACTOR = "reconciler"
#: Cuántas operaciones procesa un tick como máximo: acota el tiempo de un trabajo. Lo que quede se toma en el siguiente.
SWEEP_BATCH = 200


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def safe_error(exc: BaseException) -> str:
    """El error que se guarda y se audita: el tipo y, **solo para errores nuestros** (`AmazonaError`, `RuntimeError`,
    `ValueError`), su
    mensaje, truncado. Un error de la base o de una librería puede llevar parámetros de la sentencia: de esos solo el
    tipo."""
    from app.core.errors import AmazonaError

    if isinstance(exc, AmazonaError | RuntimeError | ValueError):
        return f"{type(exc).__name__}: {exc}"[:500]
    return type(exc).__name__


@dataclass
class ActionSweepReport:
    examined: int = 0
    released: list[str] = field(default_factory=list)
    marked_unknown: list[str] = field(default_factory=list)
    lost_race: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "examined": self.examined,
            "released": len(self.released),
            "marked_unknown": len(self.marked_unknown),
            "lost_race": self.lost_race,
            "failed": len(self.failed),
        }


class ActionReconciler:
    def __init__(
        self,
        db: Session,
        *,
        older_than: datetime.timedelta,
        clock: Callable[[], datetime.datetime] = _utcnow,
        batch: int = SWEEP_BATCH,
    ) -> None:
        self._db = db
        self._older_than = older_than
        self._clock = clock
        self._batch = batch
        self._service = ExternalActionService(db, clock=clock)

    def sweep(self, heartbeat: Callable[[], None] | None = None) -> ActionSweepReport:
        """Un barrido. `heartbeat` (el del trabajo) se llama antes de cada elemento para mantener el arriendo vivo."""
        report = ActionSweepReport()
        limit = self._clock() - self._older_than
        for action_id, _status in self._service.stale_candidates(limit, batch=self._batch):
            if heartbeat is not None:
                heartbeat()
            report.examined += 1
            try:
                outcome = self._service.sweep_one(action_id)
            except Exception as exc:  # noqa: BLE001 - un elemento que falla no puede abortar el lote
                self._db.rollback()
                logger.warning("the sweep of external action %s failed: %s", action_id, type(exc).__name__)
                report.failed.append((action_id, type(exc).__name__))
                self._audit_failure(action_id, exc)
                continue
            if outcome == "released":
                report.released.append(action_id)
            elif outcome == "unknown":
                report.marked_unknown.append(action_id)
            else:
                report.lost_race += 1
        return report

    def _audit_failure(self, action_id: str, exc: Exception) -> None:
        try:
            self._db.add(
                AuditLog(
                    actor=RECONCILER_ACTOR,
                    action="reconciliation.action_sweep_failed",
                    resource=f"external_action:{action_id}",
                    before=None,
                    after={"error": safe_error(exc)},
                    correlation_id=new_correlation_id(),
                )
            )
            self._db.commit()
        except Exception:  # noqa: BLE001 - dejar rastro del fallo no puede ser otro fallo del lote
            self._db.rollback()
