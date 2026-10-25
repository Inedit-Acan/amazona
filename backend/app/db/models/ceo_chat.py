"""La conversación escrita con el CEO (M52): conversaciones, mensajes y propuestas de acción.

Es memoria CONVERSACIONAL, a propósito separada de `memory_records` (memoria de DOMINIO: «qué sabemos de esta entidad»,
el último valor gana).
Aquí lo que importa es el rastro exacto, en orden, de lo que se dijo, de lo que se leyó (la salida de cada herramienta,
estructurada) y de lo que
se propuso; y qué propuesta confirmó o rechazó una persona.

- `ceo_conversations`: de quién es (`owner_subject`, el `sub` verificado del token: nunca una identidad que declare el
  modelo).
- `ceo_messages`: `user`, `assistant`, `tool` y `system_internal`. Este último NO se enseña nunca al usuario (guarda
  con qué versión del prompt y con
  qué contexto se respondió). La salida de una herramienta va en `structured`, no como texto suelto. Los mensajes del
  asistente llevan su uso (tokens,
  proveedor, modelo, coste estimado y su categoría): se MIDE y se expone, nunca se carga al presupuesto empresarial.
- `ceo_action_proposals`: lo que el CEO PROPONE. Proponer no ejecuta: una propuesta nace `PROPOSED` y solo una acción
  autenticada del OWNER la confirma
  o la rechaza. La que se ejecuta queda enlazada al mensaje que la propuso y al que da cuenta del resultado.
"""

import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import IdMixin, TimestampMixin

MESSAGE_ROLES = ("user", "assistant", "tool", "system_internal")
ACTION_TYPES = (
    "create_mission",
    "retry_task",
    "reassign_task",
    "resume_mission",
    "approve_approval",
    "reject_approval",
)
PROPOSAL_STATUSES = ("PROPOSED", "EXECUTING", "EXECUTED", "FAILED", "REJECTED")
RISK_LEVELS = ("low", "medium", "high")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class CeoConversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "ceo_conversations"

    #: El `sub` verificado de quien conversa. Todo acceso filtra por él: una conversación nunca se mezcla con la de otro
    #: usuario.
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CeoMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "ceo_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_ceo_messages_conversation_seq"),
        CheckConstraint(_in("role", MESSAGE_ROLES), name="ck_ceo_messages_role"),
    )

    conversation_id: Mapped[str] = mapped_column(ForeignKey("ceo_conversations.id"), index=True)
    #: Orden dentro de la conversación (1, 2, 3…). No se confía en `created_at`, que puede empatar.
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    #: Datos estructurados: la salida de una herramienta, el contexto con el que se respondió… Nunca texto
    #: descontrolado.
    structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Coste ESTIMADO de la consulta en dólares, `NULL` si no hay tarifa configurada (nunca cero inventado).
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    #: De dónde sale el coste: `claude_credits`, `external_api`… NUNCA se mezcla con el gasto comercial real ni con el
    #: cash.
    external_cost_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class CeoActionProposal(IdMixin, TimestampMixin, Base):
    __tablename__ = "ceo_action_proposals"
    __table_args__ = (
        CheckConstraint(_in("action_type", ACTION_TYPES), name="ck_ceo_action_proposals_type"),
        CheckConstraint(_in("status", PROPOSAL_STATUSES), name="ck_ceo_action_proposals_status"),
        CheckConstraint(_in("risk_level", RISK_LEVELS), name="ck_ceo_action_proposals_risk"),
    )

    conversation_id: Mapped[str] = mapped_column(ForeignKey("ceo_conversations.id"), index=True)
    #: El mensaje del asistente que la propuso (se enlaza al final del turno).
    message_id: Mapped[str | None] = mapped_column(ForeignKey("ceo_messages.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(40))
    target: Mapped[dict] = mapped_column(JSON)
    parameters: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text, default="")
    estimated_effects: Mapped[dict] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(10))
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    #: El scope de idempotencia REAL de la operación que ejecuta (`tasks.retry`, `objectives.resume`…); `NULL` si la
    #: operación es una transición
    #: con compare-and-set (aprobaciones).
    idempotency_scope: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED")
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: El mensaje que da cuenta de lo ejecutado (la acción ejecutada queda enlazada a la conversación).
    result_message_id: Mapped[str | None] = mapped_column(ForeignKey("ceo_messages.id"), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
