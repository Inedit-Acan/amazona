import datetime
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    """Estados de un trabajo (plan maestro §6).

    No confundir con `TaskStatus` (`app/tasks/schemas.py`): una `Task` es una
    unidad de trabajo del grafo del CEO —dominio—, y un `Job` es una unidad de
    ejecución del runtime —infraestructura—. Un día una Task podrá ejecutarse
    mediante uno o varios Jobs, pero son cosas distintas y las dos conservan su
    nombre.
    """

    #: Creado, todavía no elegible: su ventana de disponibilidad está en el
    #: futuro. Es donde espera un trabajo programado.
    PENDING = "PENDING"
    #: Elegible: cualquier worker puede reclamarlo.
    QUEUED = "QUEUED"
    #: Reclamado por un worker, con arriendo (lease) vivo.
    RUNNING = "RUNNING"
    #: Falló un intento y espera su ventana de reintento.
    RETRYING = "RETRYING"
    #: Parado a la espera de una decisión humana. El runtime no lo reclama:
    #: vuelve cuando alguien aprueba y lo reencola (Milestone 33, ActionGate).
    WAITING_APPROVAL = "WAITING_APPROVAL"
    #: Parado porque una condición lo impide y esperar no la arregla (kill
    #: switch apagado desde el Milestone 32; legal NO_GO y presupuesto agotado
    #: en el 33). Tampoco se reclama: vuelve cuando alguien lo reencola.
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    #: Agotó sus intentos. Es la cola de mensajes muertos: la fila sigue ahí,
    #: con todos sus intentos y su error, y se puede reencolar.
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Estados desde los que un worker puede reclamar trabajo.
CLAIMABLE: frozenset[JobStatus] = frozenset({JobStatus.QUEUED})

#: Estados finales: no vuelven a ejecutarse solos.
TERMINAL: frozenset[JobStatus] = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})

#: Estados parados a la espera de una intervención externa. El runtime los
#: ignora a propósito: no son suyos.
HELD: frozenset[JobStatus] = frozenset({JobStatus.WAITING_APPROVAL, JobStatus.BLOCKED})


class JobEventKind(StrEnum):
    """Lo que le ha pasado a un trabajo, en orden. Es su trazabilidad."""

    ENQUEUED = "enqueued"
    CLAIMED = "claimed"
    HEARTBEAT = "heartbeat"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCELLED = "cancelled"
    LEASE_EXPIRED = "lease_expired"
    REQUEUED = "requeued"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True)
class JobResult:
    """Lo que devuelve un manejador.

    `reference` no es el resultado sino dónde vive: un `correlation_id`, el id
    de una fila. El plan maestro lo pide así (§6, `result_reference`) para que
    la tabla de trabajos no se convierta en un almacén de payloads.
    """

    reference: str | None = None
    detail: dict | None = None


class JobCancelledError(Exception):
    """El trabajo se canceló mientras se ejecutaba. La lanza `heartbeat()` para
    que un manejador cooperativo pare donde esté."""


class JobBlockedError(Exception):
    """Una condición externa impide seguir, y esperar no la arregla: el kill
    switch apagado, y en el Milestone 33 un veto legal o un presupuesto agotado.

    Un manejador que la lanza deja su trabajo en `BLOCKED` en vez de gastar
    intentos: el runtime no lo reclamará, y vuelve a la cola cuando una persona
    levanta la condición (`POST /api/jobs/{id}/requeue`). Es distinto de un
    fallo —que se reintenta— y de una cancelación —que no vuelve—.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JobAwaitingApprovalError(Exception):
    """El trabajo no puede seguir hasta que una persona decida (Milestone 33).

    Lo lanza un manejador que se ha topado con una puerta —el ActionGate pidiendo
    autorización para una acción con efecto—. El trabajo queda en
    `WAITING_APPROVAL`: el runtime no lo reclama y no gasta intentos, y vuelve a
    la cola cuando alguien aprueba. Es distinto de `JobBlockedError`, que es una
    condición sin decisión humana detrás, y de un fallo, que se reintenta solo.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class JobContext:
    """Lo que un manejador recibe además de su payload."""

    job_id: str
    correlation_id: str
    attempt: int
    #: Extiende el arriendo y comprueba que el trabajo sigue siendo nuestro.
    #: Un manejador largo debe llamarlo: si no, el segador lo dará por muerto.
    #: Lanza `JobCancelledError` si mientras tanto lo han cancelado.
    heartbeat: Callable[[], None]
    started_at: datetime.datetime
