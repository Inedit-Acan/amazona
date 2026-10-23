"""La máquina de estados de una tarea (M49, Commit 8). Una transición que no está en la tabla se rechaza.

Estados que la tarea usa de verdad: PENDING, RUNNING, FAILED, BLOCKED, COMPLETED y CANCELLED.

- «ASSIGNED» NO es un estado de la tarea: la asignación es ortogonal (`assigned_agent_id`, ver
  `app/tasks/assignment.py`) y se lee como la relación tarea ↔ agente. Una tarea PENDING puede estar asignada o no.
- QUEUED, WAITING y WAITING_APPROVAL existen en el enum del dominio pero ninguna tarea los recorre: no tienen
  transiciones.

    PENDING   → RUNNING    empieza un intento
    PENDING   → BLOCKED    una dependencia FAILED/BLOCKED/CANCELLED, o el agente asignado desconocido
    PENDING   → CANCELLED
    RUNNING   → COMPLETED  el intento acabó bien
    RUNNING   → FAILED     el intento falló
    FAILED    → PENDING    se va a reintentar (automático y acotado, o explícito)
    FAILED    → CANCELLED
    BLOCKED   → PENDING    lo que bloqueaba se resolvió
    BLOCKED   → CANCELLED
    COMPLETED, CANCELLED   terminales: una tarea completada no vuelve a ejecutarse
"""

from collections.abc import Mapping

from app.core.errors import ConflictError
from app.tasks.schemas import TaskStatus

S = TaskStatus

ALLOWED_TRANSITIONS: Mapping[TaskStatus, frozenset[TaskStatus]] = {
    S.PENDING: frozenset({S.RUNNING, S.BLOCKED, S.CANCELLED}),
    S.RUNNING: frozenset({S.COMPLETED, S.FAILED}),
    S.FAILED: frozenset({S.PENDING, S.CANCELLED}),
    S.BLOCKED: frozenset({S.PENDING, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}


class InvalidTaskTransitionError(ConflictError):
    """La tarea no puede pasar de ese estado a ese otro. Es un conflicto de estado (409): no se cambió nada."""


def _status(value: str | TaskStatus) -> TaskStatus | None:
    try:
        return TaskStatus(value)
    except ValueError:
        return None


def can_transition(current: str | TaskStatus, new: str | TaskStatus) -> bool:
    origin, target = _status(current), _status(new)
    if origin is None or target is None:
        return False
    return target in ALLOWED_TRANSITIONS.get(origin, frozenset())


def ensure_transition(current: str | TaskStatus, new: str | TaskStatus) -> TaskStatus:
    """El estado nuevo, o `InvalidTaskTransitionError` si la tabla no lo permite."""
    if not can_transition(current, new):
        raise InvalidTaskTransitionError(f"a task cannot go from {current} to {new}")
    return TaskStatus(new)
