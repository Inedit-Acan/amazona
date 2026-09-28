"""El contador que autoriza y apunta cada llamada externa (Milestone 37, §25).

La parte con base de datos: lee lo consumido, le pregunta a la función pura si
cabe la llamada, y **anota la respuesta pase lo que pase**. Una denegación deja
fila igual que un permiso: es lo que explica por qué una investigación volvió sin
señales, y sin ella el sistema parecería averiado en vez de prudente.

## Por qué el contador se inyecta y no se busca

Los adaptadores ya reciben su cliente HTTP por inyección desde el Milestone 34, y
el contador viaja igual. Así un adaptador no sabe de dónde sale el presupuesto —no
importa `Settings`, no toca la base de datos— y sigue siendo probable sin red y
sin base de datos, que es la mitad del valor de un adaptador.
"""

import datetime
import logging
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AmazonaError
from app.costs.decision import CostDecision, Usage, evaluate_api_call
from app.costs.policy import SpendLimit, policy_for
from app.db.models.external_api_cost import ExternalApiCost

logger = logging.getLogger(__name__)


class ApiBudgetExceededError(AmazonaError):
    """No cabía la llamada. Quien la recibe **no produce señal**: una señal
    ausente se queda ausente, nunca se convierte en un cero (ADR 0012 §4)."""


class CallMeter(Protocol):
    """Lo que un adaptador necesita saber del contador: nada más que esto."""

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None: ...


class UnmeteredCalls(CallMeter):
    """Permite todo y no apunta nada.

    **Solo para pruebas de un adaptador en aislamiento**, donde no hay ni base de
    datos ni presupuesto que contar. En cualquier montaje real el contador lo
    inyecta el registro de proveedores, y hay un test que lo comprueba: si esto
    apareciera en producción, las llamadas se harían sin techo y sin registro.
    """

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        return None


class CostMeter(CallMeter):
    """El contador de verdad: consulta, decide y apunta."""

    def __init__(
        self,
        db: Session,
        *,
        correlation_id: str,
        limits: dict[str, SpendLimit] | None = None,
        today: datetime.date | None = None,
    ) -> None:
        self._db = db
        self._correlation_id = correlation_id
        self._limits = limits or {}
        self._today = today

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        """Deja pasar la llamada, o la corta con `ApiBudgetExceededError`.

        En los dos casos queda una fila. El commit no se hace aquí: la llamada
        vive dentro de la transacción de quien la pidió, y un contador que hiciera
        commit por su cuenta partiría en dos el trabajo que la envuelve.
        """
        policy = policy_for(provider)
        decision = evaluate_api_call(
            policy=policy,
            limit=self._limits.get(provider),
            units=units,
            usage=self._usage_of(provider),
        )
        self._record(provider, operation, units, policy.unit, decision)
        if not decision.allowed:
            logger.warning("api call denied for %s/%s: %s", provider, operation, decision.reason)
            raise ApiBudgetExceededError(decision.reason or "api call not authorised")

    # --- Lo consumido -------------------------------------------------------

    def _usage_of(self, provider: str) -> Usage:
        """Lo gastado hoy y en esta ejecución. Solo cuentan las llamadas
        permitidas: una denegada no consumió nada de nadie."""
        start = datetime.datetime.combine(
            self._today or datetime.datetime.now(datetime.UTC).date(),
            datetime.time.min,
            tzinfo=datetime.UTC,
        )
        today = self._db.execute(
            select(
                func.coalesce(func.sum(ExternalApiCost.units), 0),
                func.coalesce(func.sum(ExternalApiCost.estimated_cost), 0.0),
            ).where(
                ExternalApiCost.provider == provider,
                ExternalApiCost.outcome == "allowed",
                ExternalApiCost.observed_at >= start,
            )
        ).one()
        run = self._db.execute(
            select(
                func.coalesce(func.sum(ExternalApiCost.units), 0),
                func.coalesce(func.sum(ExternalApiCost.estimated_cost), 0.0),
            ).where(
                ExternalApiCost.provider == provider,
                ExternalApiCost.outcome == "allowed",
                ExternalApiCost.correlation_id == self._correlation_id,
            )
        ).one()
        return Usage(
            units_this_run=int(run[0]),
            units_today=int(today[0]),
            cost_today=float(today[1]),
            cost_this_run=float(run[1]),
        )

    def _record(
        self, provider: str, operation: str, units: int, unit: str, decision: CostDecision
    ) -> None:
        self._db.add(
            ExternalApiCost(
                provider=provider,
                operation=operation,
                units=units,
                unit=unit,
                estimated_cost=decision.estimated_cost,
                # El coste real lo dirá el proveedor, si lo dice. Nulo no es cero.
                actual_cost=None,
                currency=decision.currency,
                outcome="allowed" if decision.allowed else "denied",
                denied_reason=decision.reason,
                correlation_id=self._correlation_id,
            )
        )
        self._db.flush()
