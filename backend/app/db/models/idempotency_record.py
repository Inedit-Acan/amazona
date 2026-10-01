import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class IdempotencyRecord(IdMixin, Base):
    """Una petición con efecto que llegó con `Idempotency-Key` (hardening pre-M44, ADR 0025).

    La identidad de la petición es `(scope, actor_hash, key)`: `scope` es la operación (`research.run`,
    `fx.refresh`…), `actor_hash` una huella de quien la pide y `key` la clave del cliente. Dos operaciones
    distintas, o dos personas distintas, no pueden chocar aunque elijan la misma clave. El `request_hash` es la
    huella del contenido de la petición: la misma clave con otro contenido es otra petición escondida tras la
    misma clave y se rechaza.

    - `IN_PROGRESS`: la reclamó alguien y no ha terminado (o su proceso cayó a medias).
    - `COMPLETED`: terminó; `response_status` y `response_body` son lo que se devolvió y lo que se devuelve de
      nuevo, sin ejecutar nada.
    - `UNKNOWN_OUTCOME`: falló de una forma que no dice si llegó a producir efecto.

    **No caduca.** Una clave sin terminar o de resultado desconocido bloquea su reutilización para siempre en vez
    de «volver a estar disponible con el tiempo»: un TTL convertiría «hace mucho» en «no ocurrió», y repetiría un
    efecto que quizá sí ocurrió.

    La garantía es el índice único de la base de datos, no una consulta previa: de N peticiones iguales a la vez,
    solo una inserta la fila.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        sa.UniqueConstraint("scope", "actor_hash", "key", name="uq_idempotency_records_scope_actor_key"),
    )

    scope: Mapped[str] = mapped_column(sa.String(64))
    actor_hash: Mapped[str] = mapped_column(sa.String(32))
    key: Mapped[str] = mapped_column(sa.String(128))
    request_hash: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(20), default="IN_PROGRESS")
    response_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    response_body: Mapped[dict | list | None] = mapped_column(sa.JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.String(2000), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
