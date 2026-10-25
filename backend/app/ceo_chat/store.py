"""Escritura de mensajes y de auditoría del chat con el CEO (M52): lo mínimo común del servicio y de las acciones.

Nada aquí hace `commit`: lo hace quien orquesta el turno, para que un turno deje sus filas juntas o ninguna.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.ceo_chat.redaction import redact, redact_text
from app.db.models.audit import AuditLog
from app.db.models.ceo_chat import CeoConversation, CeoMessage


def next_seq(db: Session, conversation_id: str) -> int:
    """El siguiente número de mensaje. Bloquea la fila de la conversación (`SELECT … FOR UPDATE`) hasta el próximo
    `commit`: dos mensajes a la vez en la misma
    conversación (dos pestañas) se numeran uno detrás de otro en vez de chocar con la clave única `(conversation_id,
    seq)`. En SQLite no hace nada."""
    db.execute(select(CeoConversation.id).where(CeoConversation.id == conversation_id).with_for_update())
    return (db.scalar(select(func.max(CeoMessage.seq)).where(CeoMessage.conversation_id == conversation_id)) or 0) + 1


def add_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str = "",
    structured: dict[str, Any] | None = None,
    **fields: Any,
) -> CeoMessage:
    """Guarda un mensaje. Es la ÚNICA puerta: el contenido y lo estructurado pasan por el redactor de siempre antes de
    llegar a la base (y, como el modelo y el frontend leen lo guardado, antes de llegar a ellos). Un secreto pegado
    por el propietario o repetido por el modelo no se conserva; el resto se guarda idéntico."""
    message = CeoMessage(
        conversation_id=conversation_id,
        seq=next_seq(db, conversation_id),
        role=role,
        content=redact_text(content),
        structured=redact(structured) if structured is not None else None,
        **fields,
    )
    db.add(message)
    db.flush()
    return message


def audit(db: Session, actor: Actor, action: str, resource: str, after: dict[str, Any], correlation_id: str) -> None:
    """El evento de auditoría del chat. Actor = el `sub` verificado (no el correo). `after` se redacta y NUNCA lleva
    texto de mensajes: ids, recuentos y
    nombres de herramienta."""
    db.add(
        AuditLog(
            actor=actor.subject,
            actor_role=actor.role.value if actor.role else None,
            actor_source=actor.source.value,
            action=action,
            resource=resource,
            before=None,
            after=redact(after),
            correlation_id=correlation_id,
        )
    )
