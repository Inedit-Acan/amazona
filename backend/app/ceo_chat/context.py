"""El contexto con el que responde el CEO (M52): una foto breve y REDACTADA del sistema, construida en cada turno con
datos reales.

Es lo que el modelo sabe SIN llamar a ninguna herramienta: el presupuesto, cuántas misiones hay y en qué estado, qué
bloquea la última. Es deliberadamente
pequeña y acotada (`MAX_CONTEXT_CHARS`): para el detalle (una tarea, el historial de decisiones, la auditoría) el
modelo usa las herramientas de lectura.
Nunca lleva la entrada de las tareas, el contexto de los objetivos, evidencias, correos ni secretos.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.ceo_chat import readers
from app.ceo_chat.redaction import redact

MAX_CONTEXT_CHARS = 3000

#: Las fuentes del contexto, tal como se las enseñamos al usuario.
CONTEXT_SOURCES = ("Presupuesto", "Estado general")


def build_context(db: Session, manager: AgentManager) -> tuple[str, list[str]]:
    """(texto del contexto, fuentes). Si una lectura falla, esa parte dice «No disponible»: el chat no se cae por el
    contexto."""
    parts: dict[str, Any] = {}
    try:
        parts["budget"] = readers.read_budget(db)
    except Exception:
        parts["budget"] = "No disponible"
    try:
        status = readers.read_system_status(db, manager)
        incomplete = status["missions"]["incomplete"]
        parts["missions"] = {
            "recent_reviewed": status["missions"]["recent_reviewed"],
            "complete": status["missions"]["complete"],
            "incomplete": [
                {
                    "objective_id": m["objective_id"],
                    "project_id": m["project_id"],
                    "title": m["title"],
                    "state": m["state"],
                    "pending_tasks": m["pending_tasks"],
                    "blockers": m["blockers"],
                }
                for m in incomplete[:3]
            ],
        }
        parts["tasks_by_status"] = status["tasks_by_status"]
        parts["pending_approvals"] = status["pending_approvals"]
    except Exception:
        parts["missions"] = "No disponible"
    text = json.dumps(redact(parts), ensure_ascii=False, sort_keys=True)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[:MAX_CONTEXT_CHARS] + "…[recortado]"
    return text, list(CONTEXT_SOURCES)
