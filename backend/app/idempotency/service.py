"""Idempotencia genérica de las rutas síncronas con efecto (hardening pre-M44, ADR 0025).

`POST /api/pipeline/runs` ya tenía la suya (ADR 0022), apoyada en la clave única del trabajo que encola. Las demás
rutas con efecto responden en la misma petición y no tienen un recurso con clave: esta es la pieza común.

    claim (INSERT + COMMIT) ─▶ work() ─▶ complete(status, body)   la siguiente igual recibe ese body
        ya existe:  mismo contenido y COMPLETED ─▶ replay
                    otro contenido ─▶ 409 · IN_PROGRESS o UNKNOWN_OUTCOME ─▶ 409
        work() lanza AmazonaError / HTTPException ─▶ release (no se hizo nada: la clave vuelve a servir)
        work() lanza otra cosa ─▶ UNKNOWN_OUTCOME (la clave no vuelve a servir)

La garantía es el índice único `(scope, actor_hash, key)`: de N peticiones iguales a la vez, la base de datos deja
insertar a una. La reclamación se confirma **antes** de ejecutar para que las demás la vean.

No hay caducidad: una clave que no llegó a completarse **no vuelve a estar disponible con el tiempo**. Un TTL
confundiría «hace mucho» con «no ocurrió» y repetiría un efecto que quizá sí ocurrió.
"""

import datetime
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar

from fastapi import Header, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.core.config import Settings
from app.core.errors import (
    AmazonaError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyOutcomeUnknownError,
    ValidationError,
)
from app.db.models.idempotency_record import IdempotencyRecord

IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9._:\-]{1,128}")

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"
UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        description="Identifica esta petición: repetirla con la misma clave y el mismo contenido devuelve la "
        "respuesta original sin volver a ejecutarla; con otro contenido, 409. Obligatoria si la operación puede "
        "tener un efecto fuera del sistema (428 si falta).",
    ),
]

T = TypeVar("T")


def actor_scope(identity: Actor) -> str:
    """Una huella de quien pide: la clave que envía el cliente es solo suya."""
    return hashlib.sha256(identity.subject.encode("utf-8")).hexdigest()[:16]


def validated_key(client_key: str | None, settings: Settings, *, always_required: bool = False) -> str | None:
    """La clave del cliente, validada, o `None` si no hay y no es obligatoria. Obligatoria siempre que la operación
    pueda tener un efecto fuera del sistema (`Settings.idempotency_key_required`), y **siempre** —también en una
    simulación— si la ruta mueve dinero (`always_required`, ADR 0028 §9)."""
    if client_key is None or client_key.strip() == "":
        if always_required or settings.idempotency_key_required:
            raise IdempotencyKeyRequiredError(
                "this operation can have an effect outside the system: send an Idempotency-Key header "
                "so that retrying it after a timeout cannot run it twice"
            )
        return None
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(client_key):
        raise ValidationError("Idempotency-Key must be 1-128 characters of letters, digits, '.', '_', ':' or '-'")
    return client_key


def request_hash(payload: Any) -> str:
    """La huella del contenido: la misma petición da siempre la misma, sea cual sea el orden de sus campos."""
    canonical = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Replay:
    """Lo que se devolvió la primera vez."""

    status_code: int
    body: Any


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class IdempotencyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def claim(self, *, scope: str, actor: str, key: str, payload: Any) -> IdempotencyRecord | Replay:
        """Reclama la clave —y la confirma— o devuelve lo que ya se respondió. Lanza 409 si la clave ya se usó
        con otro contenido, o si la petición anterior no terminó."""
        digest = request_hash(payload)
        for _ in range(3):
            record = IdempotencyRecord(scope=scope, actor_hash=actor, key=key, request_hash=digest)
            try:
                with self._db.begin_nested():
                    self._db.add(record)
                    self._db.flush()
            except IntegrityError:
                existing = self._existing(scope, actor, key)
                if existing is None:  # quien la tenía la liberó entre medias: se vuelve a intentar
                    continue
                return self._answer(existing, digest)
            self._db.commit()
            return record
        raise IdempotencyInProgressError("could not claim this Idempotency-Key: try again")

    def complete(self, record: IdempotencyRecord, *, status_code: int, body: Any) -> None:
        """Guarda lo que se devolvió. La fila es de quien la reclamó: nadie más la toca mientras está en curso."""
        self._db.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record.id, IdempotencyRecord.status == IN_PROGRESS)
            .values(status=COMPLETED, response_status=status_code, response_body=body, completed_at=_utcnow())
        )
        self._db.commit()

    def release(self, record: IdempotencyRecord) -> None:
        """La petición fue rechazada sin hacer nada: la clave vuelve a servir."""
        self._db.rollback()
        self._db.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.id == record.id, IdempotencyRecord.status == IN_PROGRESS)
        )
        self._db.commit()

    def mark_unknown(self, record: IdempotencyRecord, error: str) -> None:
        """Falló de una forma que no dice si llegó a producir efecto: la clave deja de servir."""
        self._db.rollback()
        self._db.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record.id, IdempotencyRecord.status == IN_PROGRESS)
            .values(status=UNKNOWN_OUTCOME, error=error[:2000], completed_at=_utcnow())
        )
        self._db.commit()

    # --- Interno ---------------------------------------------------------------------

    def _existing(self, scope: str, actor: str, key: str) -> IdempotencyRecord | None:
        self._db.expire_all()
        return self._db.query(IdempotencyRecord).filter_by(scope=scope, actor_hash=actor, key=key).one_or_none()

    @staticmethod
    def _answer(existing: IdempotencyRecord, digest: str) -> Replay:
        if existing.request_hash != digest:
            raise IdempotencyConflictError(
                "this Idempotency-Key was already used for a different request: use a new key for a new request"
            )
        if existing.status == COMPLETED:
            return Replay(status_code=existing.response_status or 200, body=existing.response_body)
        if existing.status == UNKNOWN_OUTCOME:
            raise IdempotencyOutcomeUnknownError(
                "the request that used this Idempotency-Key failed in a way that does not say whether it took "
                "effect: check what happened and use a new key"
            )
        raise IdempotencyInProgressError(
            "a request with this Idempotency-Key is still being processed, or its process stopped before "
            "finishing: wait for it, or check what happened and use a new key"
        )


def run_idempotent(
    db: Session,
    *,
    scope: str,
    identity: Actor,
    client_key: str | None,
    settings: Settings,
    payload: Any,
    response: Response,
    status_code: int,
    response_model: type[BaseModel],
    work: Callable[[], T],
    always_required: bool = False,
) -> T | Any:
    """Ejecuta `work` una sola vez por `(scope, actor, key)` y devuelve lo mismo a quien repita la petición.

    Sin clave (y solo cuando no es obligatoria) la operación se ejecuta como siempre: no se inventa una."""
    key = validated_key(client_key, settings, always_required=always_required)
    if key is None:
        return work()

    service = IdempotencyService(db)
    claimed = service.claim(scope=scope, actor=actor_scope(identity), key=key, payload=payload)
    if isinstance(claimed, Replay):
        response.status_code = claimed.status_code
        response.headers["Idempotency-Replayed"] = "true"
        return claimed.body

    try:
        result = work()
    except (AmazonaError, HTTPException):
        # Una negativa del dominio (no existe, no es válido, la fuente no respondió y no se guardó nada): no hubo
        # efecto, así que la clave vuelve a servir.
        service.release(claimed)
        raise
    except Exception as exc:
        service.mark_unknown(claimed, f"{type(exc).__name__}: {exc}")
        raise
    try:
        body = jsonable_encoder(response_model.model_validate(result, from_attributes=True))
        service.complete(claimed, status_code=status_code, body=body)
    except Exception as exc:
        # El efecto ya ocurrió y no se pudo dejar su respuesta: repetirlo no es una opción.
        service.mark_unknown(claimed, f"{type(exc).__name__}: {exc}")
        raise
    return result
