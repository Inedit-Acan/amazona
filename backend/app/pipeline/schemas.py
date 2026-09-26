"""Estados y orden de los pasos del pipeline (Milestone 32, ADR 0010).

Aquí viven los dos vocabularios que antes estaban escritos a mano en cadenas
sueltas: en qué estado está una ejecución y en qué estado está cada uno de sus
nueve pasos.

No confundir con `JobStatus` (`app/jobs/schemas.py`): un `Job` es la unidad de
ejecución del runtime —quién lo tiene, cuántos intentos le quedan— y un
`PipelineRun` es el trabajo de negocio que ese job lleva a cabo. Un job puede
reintentarse tres veces mientras la ejecución sigue siendo la misma, y una
ejecución puede sobrevivir a que su job muera.
"""

from enum import StrEnum


class PipelineRunStatus(StrEnum):
    """En qué estado está una ejecución del pipeline."""

    #: Encolada: existe la fila y su trabajo, pero ningún worker la ha tocado.
    QUEUED = "QUEUED"
    #: Un worker la está ejecutando paso a paso.
    RUNNING = "RUNNING"
    #: Los nueve pasos terminaron.
    COMPLETED = "COMPLETED"
    #: Un paso no pudo entregar nada al siguiente (research sin candidatos).
    #: Es un resultado de negocio, no un fallo técnico: no se reintenta solo,
    #: porque volver a preguntar lo mismo daría lo mismo. ADR 0006 lo trata como
    #: motivo de revisión humana.
    PARTIAL = "PARTIAL"
    #: Un paso reventó. Sí es un fallo técnico: el runtime lo reintenta con
    #: espera, y al reanudar se sigue por el paso que falló.
    FAILED = "FAILED"
    #: Parada porque el kill switch estaba apagado cuando le llegó el turno.
    #: Ningún paso se tocó; se reanuda cuando un operador lo reactiva.
    BLOCKED = "BLOCKED"
    #: Una persona la paró. No vuelve por su cuenta.
    CANCELLED = "CANCELLED"


class PipelineStepStatus(StrEnum):
    """En qué estado está un paso concreto de una ejecución (plan maestro §21)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    #: No se ejecutó a propósito: la ejecución se quedó en PARTIAL antes de
    #: llegar aquí. Decirlo es distinto de dejarlo en PENDING, que significaría
    #: «todavía le puede tocar».
    SKIPPED = "SKIPPED"
    #: Estaba en marcha cuando alguien canceló la ejecución.
    CANCELLED = "CANCELLED"


#: Los nueve pasos de Fase 3, en el único orden en que pueden ocurrir: cada uno
#: necesita el id real que produjo el anterior (ADR 0005).
STEP_ORDER: tuple[str, ...] = (
    "research",
    "sourcing",
    "economics",
    "legal",
    "ecommerce",
    "marketplace",
    "marketing",
    "operations",
    "cfo",
)

#: Estados de una ejecución que ya no van a moverse solos, pero de los que sí se
#: puede reanudar: el trabajo válido que hicieron se conserva.
RESUMABLE: frozenset[PipelineRunStatus] = frozenset(
    {
        PipelineRunStatus.FAILED,
        PipelineRunStatus.PARTIAL,
        PipelineRunStatus.BLOCKED,
        PipelineRunStatus.CANCELLED,
    }
)

#: Estados desde los que cancelar significa algo: o no ha empezado, o está en
#: marcha, o está reintentando. Cancelar algo ya terminado no.
CANCELLABLE: frozenset[PipelineRunStatus] = frozenset(
    {
        PipelineRunStatus.QUEUED,
        PipelineRunStatus.RUNNING,
        PipelineRunStatus.FAILED,
        PipelineRunStatus.BLOCKED,
    }
)


def step_ordinal(name: str) -> int:
    """Posición de un paso en la cadena. `ValueError` si no es uno de los nueve."""
    return STEP_ORDER.index(name)
