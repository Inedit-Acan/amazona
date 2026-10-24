"""Fault injection de ENSAYO (M51A): hacer fallar UNA vez UNA tarea concreta de UNA misión, para probar la recuperación.

**No es una capacidad de producción.** Está apagado por defecto (`fault_injection_enabled = false`) y, encendido,
solo existe en `development` con todos los proveedores simulados: en cualquier otro entorno el arranque falla
(`Settings.validate_for_startup`).

Qué hace y qué NO hace:

- Un armado es EXACTAMENTE `(objective_id, task_name, attempt)`: sin comodines, sin patrones, sin armados globales.
  Solo las tareas de una lista cerrada (`ALLOWED_TASKS`): nada de finanzas, nada de la síntesis, nada con proveedor
  externo o gasto.
- De UN solo uso: se consume ANTES de lanzar la excepción. Caduca (`FAULT_TTL`). Vive SOLO en la memoria del
  proceso: no hay tabla ni fichero, y un reinicio lo borra (el estado seguro es «nada armado»). Solo puede haber UN
  armado a la vez.
- Se dispara en un único punto, `AgentManager.execute`, ANTES de ejecutar al agente: el agente no corre, no se llama
  a ningún proveedor y no se toca el presupuesto. Lo que lanza es `InjectedFault`, con un texto fijo y sin datos de
  nadie.
- `InjectedFault` indica `inline_retry = False`: el orquestador la trata (y solo a ella) con `max_retries = 0`, de
  modo que la tarea queda FAILED tras UN intento y el reintento explícito de Commit 8 sigue disponible. Cualquier
  otro fallo sigue la política de siempre.
- Auditable en el `audit_log` de siempre: `fault.armed` (la ruta), `fault.fired` (quien captura la excepción, en la
  misma transacción que el fallo de la tarea) y `fault.expired` (la primera operación con base de datos que se
  entera de que caducó).

Limitación conocida: es estado de proceso. Con varios procesos servidor, el armado solo vale para el que lo recibió:
el ensayo se hace con uno solo.
"""

import datetime
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationError
from app.db.models.audit import AuditLog
from app.tasks.schemas import Task

#: Las tareas del plan que se pueden hacer fallar y la capacidad que cada una tiene que declarar. Lista CERRADA: no
#: incluye `finance_validation` (`financial_validation`) ni `decision_synthesis`, ni nada con un proveedor externo o con
#: posibilidad de gasto.
ALLOWED_TASKS: dict[str, str] = {
    "product_validation": "market_validation",
    "supplier_sourcing": "supplier_sourcing",
    "legal_validation": "legal_validation",
}

#: Cuánto vive un armado si no se dispara.
FAULT_TTL = datetime.timedelta(minutes=30)
#: El intento más alto que se puede armar (el tope por asignación de la política de recuperación).
MAX_ATTEMPT = 3
#: Lo único que dice la excepción: sin datos de usuario.
FIXED_MESSAGE = "injected fault (test only)"

#: Un objetivo se nombra EXACTAMENTE: ni comodines ni patrones (un id de objetivo no tiene más caracteres que estos).
OBJECTIVE_ID_PATTERN = r"[A-Za-z0-9_-]{1,64}"
_OBJECTIVE_ID = re.compile(OBJECTIVE_ID_PATTERN)
ACTOR = "fault-injection"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass(frozen=True)
class ArmedFault:
    objective_id: str
    task_name: str
    attempt: int
    armed_by: str
    armed_at: datetime.datetime
    expires_at: datetime.datetime
    #: La correlación del armado (`fault.armed` y, si caduca, `fault.expired`).
    correlation_id: str

    def audit_after(self) -> dict[str, object]:
        return {
            "objective_id": self.objective_id,
            "task": self.task_name,
            "attempt": self.attempt,
            "armed_by": self.armed_by,
            "armed_at": self.armed_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class InjectedFault(RuntimeError):
    """El fallo de ensayo. Lo captura el orquestador (o el reintento) como cualquier fallo de un agente, salvo que NO se
    reintenta en línea."""

    #: Lo único que cambia respecto a un fallo normal: la tarea queda FAILED tras este intento.
    inline_retry = False

    def __init__(self, armed: ArmedFault, fired_at: datetime.datetime) -> None:
        super().__init__(FIXED_MESSAGE)
        self.armed = armed
        self.fired_at = fired_at

    def audit_after(self) -> dict[str, object]:
        return {
            "objective_id": self.armed.objective_id,
            "task": self.armed.task_name,
            "attempt": self.armed.attempt,
            "armed_by": self.armed.armed_by,
            "armed_at": self.armed.armed_at.isoformat(),
            "fired_at": self.fired_at.isoformat(),
            "armed_correlation_id": self.armed.correlation_id,
        }


class FaultInjector:
    """El armado en memoria. Seguro entre hilos."""

    def __init__(self, clock: Callable[[], datetime.datetime] | None = None) -> None:
        self._clock = clock or _utcnow
        self._lock = threading.RLock()
        self._armed: ArmedFault | None = None
        self._expired: list[ArmedFault] = []

    def arm(self, *, objective_id: str, task_name: str, attempt: int, armed_by: str, correlation_id: str) -> ArmedFault:
        if not isinstance(objective_id, str) or _OBJECTIVE_ID.fullmatch(objective_id) is None:
            raise ValidationError("a fault is armed for one objective, named exactly: no patterns, no wildcards")
        if task_name not in ALLOWED_TASKS:
            raise ValidationError(
                f"task {task_name!r} cannot be made to fail: allowed tasks are {sorted(ALLOWED_TASKS)}"
            )
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= MAX_ATTEMPT:
            raise ValidationError(f"the attempt has to be an integer between 1 and {MAX_ATTEMPT}")
        if not isinstance(armed_by, str) or not armed_by.strip():
            raise ValidationError("a fault is armed by someone: the actor is required")
        with self._lock:
            self.purge_expired()
            if self._armed is not None:
                raise ConflictError("a fault is already armed: it has to fire or expire before another one is armed")
            now = self._clock()
            fault = ArmedFault(
                objective_id=objective_id,
                task_name=task_name,
                attempt=attempt,
                armed_by=armed_by,
                armed_at=now,
                expires_at=now + FAULT_TTL,
                correlation_id=correlation_id,
            )
            self._armed = fault
            return fault

    def check(self, task: Task, *, allowed: bool) -> InjectedFault | None:
        """¿Hay que hacer fallar esta ejecución? Solo con la tripleta EXACTA, una vez. El armado se consume AQUÍ,
        antes de que nadie lance nada. Con la funcionalidad no permitida no actúa y no deja nada armado."""
        with self._lock:
            fault = self._armed
            if fault is None:
                return None
            if not allowed:
                self._armed = None
                return None
            now = self._clock()
            if now >= fault.expires_at:
                self._armed = None
                self._expired.append(fault)
                return None
            matches = (
                task.objective_id == fault.objective_id
                and task.name == fault.task_name
                and task.capability == ALLOWED_TASKS[fault.task_name]
                and task.retry_count + 1 == fault.attempt
            )
            if not matches:
                return None
            self._armed = None
            return InjectedFault(fault, now)

    def has_armed(self) -> bool:
        return self._armed is not None

    def armed(self) -> list[ArmedFault]:
        with self._lock:
            self.purge_expired()
            return [] if self._armed is None else [self._armed]

    def purge_expired(self) -> None:
        """Lo que caducó sin dispararse sale del estado y queda pendiente de auditar (`take_expired`)."""
        with self._lock:
            if self._armed is not None and self._clock() >= self._armed.expires_at:
                self._expired.append(self._armed)
                self._armed = None

    def take_expired(self) -> list[ArmedFault]:
        with self._lock:
            expired, self._expired = self._expired, []
            return expired

    def disarm(self, fault: ArmedFault) -> None:
        """Solo para deshacer un armado cuya auditoría no se pudo confirmar. No hay ninguna ruta que lo exponga."""
        with self._lock:
            if self._armed == fault:
                self._armed = None

    def has_pending(self) -> bool:
        return self._armed is not None or bool(self._expired)


_injector = FaultInjector()


def get_fault_injector() -> FaultInjector:
    return _injector


def set_fault_injector(injector: FaultInjector) -> FaultInjector:
    """Sustituye el inyector del proceso (las pruebas, y simular un reinicio: el nuevo empieza vacío)."""
    global _injector
    _injector = injector
    return injector


def drain_expired_audit(db: Session) -> None:
    """Escribe `fault.expired` para lo que caducó sin dispararse, UNA vez. Lo llaman las operaciones que ya tienen una
    transacción (armar, ejecutar una misión, reintentar, reanudar): no hay temporizador ni trabajo en segundo plano."""
    injector = get_fault_injector()
    if not injector.has_pending():
        return
    injector.purge_expired()
    for fault in injector.take_expired():
        db.add(
            AuditLog(
                actor=ACTOR,
                action="fault.expired",
                resource=f"objective:{fault.objective_id}",
                before=None,
                after=fault.audit_after(),
                correlation_id=fault.correlation_id,
            )
        )
