"""Qué sabe hacer el runtime.

Un manejador es una función `(payload, context, db) -> JobResult`. Se registran
por nombre, y un trabajo cuyo tipo no está registrado falla de inmediato en vez
de quedarse dando vueltas en la cola: un tipo desconocido es un error de
despliegue, no algo que el tiempo arregle.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.jobs.schemas import JobContext, JobResult

JobHandler = Callable[[dict, JobContext, Session], JobResult]

_HANDLERS: dict[str, JobHandler] = {}


class UnknownJobTypeError(LookupError):
    """No hay manejador registrado para ese tipo."""


def register(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(handler: JobHandler) -> JobHandler:
        if job_type in _HANDLERS:
            raise ValueError(f"job type {job_type} is already registered")
        _HANDLERS[job_type] = handler
        return handler

    return decorator


def resolve(job_type: str) -> JobHandler:
    handler = _HANDLERS.get(job_type)
    if handler is None:
        known = ", ".join(sorted(_HANDLERS)) or "none"
        raise UnknownJobTypeError(f"no handler registered for {job_type}; known: {known}")
    return handler


def known_types() -> list[str]:
    return sorted(_HANDLERS)
