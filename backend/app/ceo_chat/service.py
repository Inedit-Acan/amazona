"""El servicio de chat con el CEO (M52): un turno de conversación, de punta a punta.

    mensaje del propietario ─▶ se guarda ─▶ contexto real (redactado) + historial ─▶ MODELO
        ◀─ el modelo pide herramientas ─▶ se VALIDAN (lista cerrada, esquema estricto) ─▶ lecturas se ejecutan /
        escrituras se PROPONEN
        ◀─ resultado redactado ─▶ MODELO ─▶ … (como mucho `ceo_chat_max_tool_rounds` rondas) ─▶ respuesta ─▶ se guarda

Lo que este servicio NO hace, por diseño: ejecutar una escritura. `propose_*` crea una propuesta `PROPOSED` y nada más;
confirmarla es un acto autenticado
del propietario (`actions.ActionService.confirm`) al que el modelo no llega por ninguna herramienta. Tampoco lee más
que lo que `readers` expone, ni deja
pasar al modelo ni a la base algo sin redactar.

El proveedor del modelo es una dependencia (`CEOModelProvider`): sin él (`None`) o si cae, el mensaje del propietario
ya está guardado y se lanza
`ModelUnavailableError`; el resto del panel sigue funcionando.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.auth.actor import Actor
from app.ceo_chat import actions, readers, store
from app.ceo_chat.context import build_context
from app.ceo_chat.prompt import CEO_PROMPT_VERSION, system_prompt
from app.ceo_chat.provider import (
    CEOModelProvider,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelUnavailableError,
    ToolCall,
    Usage,
)
from app.ceo_chat.redaction import redact, redact_text
from app.ceo_chat.tools import PROPOSE_TOOLS, TOOLS, ToolRejected, parse_arguments, tool_specs
from app.core.config import Settings
from app.core.errors import AmazonaError, NotFoundError, ValidationError
from app.core.ids import new_correlation_id
from app.db.models.ceo_chat import CeoActionProposal, CeoConversation, CeoMessage

#: Un mensaje del propietario no puede ser un documento: el chat es para preguntar y decidir.
MAX_USER_CHARS = 2000
TRUNCATED = "[recortado]"
#: Lo que un resultado de herramienta puede ocupar en la petición al modelo.
MAX_TOOL_RESULT_CHARS = 8000
#: El modelo se quedó sin `max_tokens` (el pensamiento también cuenta): lo que haya dicho NO es una respuesta completa.
OUTPUT_LIMIT_NOTE = (
    "Respuesta incompleta: el modelo alcanzó el límite de salida antes de terminar. "
    "Reformula la pregunta de forma más concreta."
)
MODEL_REFUSAL = "No puedo responder a esta consulta: el modelo la ha rechazado. Reformúlala o acótala."
TOOL_ROUNDS_EXCEEDED = (
    "He necesitado demasiadas consultas de herramientas para responder y me he detenido. "
    "Reformula la pregunta o acótala (por ejemplo, nombra la misión o la tarea)."
)

#: Cómo se llama cada lectura ante el propietario: las FUENTES de una respuesta.
SOURCE_LABELS = {
    "get_system_status": "Estado general",
    "get_latest_mission": "Última misión",
    "get_budget_status": "Presupuesto",
    "get_pending_approvals": "Aprobaciones",
    "get_task_details": "Tarea",
    "get_decision_history": "Decisiones",
    "get_audit_summary": "Auditoría",
}


class ChatUnavailableError(ModelUnavailableError):
    """El modelo no pudo responder a ESTE mensaje. Lleva la conversación: el mensaje del propietario ya está guardado y
    la interfaz puede seguir en ella."""

    def __init__(self, message: str, conversation_id: str) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id


@dataclass
class ChatTurn:
    conversation: CeoConversation
    user_message: CeoMessage
    assistant_message: CeoMessage
    proposals: list[CeoActionProposal]
    sources: list[str]
    usage: dict[str, Any]
    tool_messages: list[CeoMessage] = field(default_factory=list)


@dataclass
class _Totals:
    rounds: int = 0
    tool_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str | None = None
    model: str | None = None
    cost_category: str | None = None
    proposals: list[CeoActionProposal] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    tool_messages: list[CeoMessage] = field(default_factory=list)
    stopped: str | None = None

    def add(self, response: ModelResponse) -> None:
        self.rounds += 1
        usage: Usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.provider, self.model, self.cost_category = response.provider, response.model, response.cost_category


def message_view(message: CeoMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "seq": message.seq,
        "role": message.role,
        "content": message.content,
        "structured": message.structured,
        "provider": message.provider,
        "model": message.model,
        "input_tokens": message.input_tokens,
        "output_tokens": message.output_tokens,
        "estimated_cost_usd": float(message.estimated_cost_usd) if message.estimated_cost_usd is not None else None,
        "external_cost_category": message.external_cost_category,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def proposal_view(proposal: CeoActionProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "conversation_id": proposal.conversation_id,
        "message_id": proposal.message_id,
        "action_type": proposal.action_type,
        "target": proposal.target,
        "parameters": proposal.parameters,
        "reason": proposal.reason,
        "estimated_effects": proposal.estimated_effects,
        "risk_level": proposal.risk_level,
        "requires_confirmation": proposal.requires_confirmation,
        "idempotency_scope": proposal.idempotency_scope,
        "status": proposal.status,
        "resolved_at": proposal.resolved_at.isoformat() if proposal.resolved_at else None,
        "execution_result": proposal.execution_result,
        "error": proposal.error,
        "result_message_id": proposal.result_message_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
    }


class CEOChatService:
    def __init__(
        self, db: Session, *, provider: CEOModelProvider | None, manager: AgentManager, settings: Settings
    ) -> None:
        self.db = db
        self.provider = provider
        self.manager = manager
        self.settings = settings

    # --- Un turno
    # ------------------------------------------------------------------------------------------------

    def chat(self, *, actor: Actor, text: str, conversation_id: str | None) -> ChatTurn:
        text = (text or "").strip()
        if not text:
            raise ValidationError("the message is empty")
        if len(text) > MAX_USER_CHARS:
            raise ValidationError(f"the message is too long: at most {MAX_USER_CHARS} characters")
        correlation_id = new_correlation_id()
        conversation, created = self._conversation(actor, conversation_id, text)
        if created:
            store.audit(
                self.db,
                actor,
                "ceo.chat_started",
                f"ceo_conversation:{conversation.id}",
                {"conversation_id": conversation.id},
                correlation_id,
            )
        user_message = store.add_message(self.db, conversation.id, "user", text, correlation_id=correlation_id)
        store.audit(
            self.db,
            actor,
            "ceo.message_received",
            f"ceo_conversation:{conversation.id}",
            {"conversation_id": conversation.id, "message_id": user_message.id, "chars": len(text)},
            correlation_id,
        )
        self.db.commit()
        try:
            if self.provider is None:
                raise ModelUnavailableError("the CEO chat has no model provider configured")
            return self._run_turn(actor, conversation, user_message, correlation_id)
        except Exception as exc:
            # Lo no confirmado se descarta (el mensaje del propietario ya está guardado), y se deja constancia sin texto
            # de mensajes.
            self.db.rollback()
            store.audit(
                self.db,
                actor,
                "ceo.response_failed",
                f"ceo_conversation:{conversation.id}",
                {"conversation_id": conversation.id, "error_class": type(exc).__name__},
                correlation_id,
            )
            self.db.commit()
            if isinstance(exc, ModelUnavailableError) and not isinstance(exc, ChatUnavailableError):
                raise ChatUnavailableError(str(exc), conversation.id) from exc
            raise

    def _run_turn(
        self, actor: Actor, conversation: CeoConversation, user_message: CeoMessage, correlation_id: str
    ) -> ChatTurn:
        assert self.provider is not None
        context_text, context_sources = build_context(self.db, self.manager)
        system = system_prompt(context_text)
        messages = self._fit(system, self._history(conversation.id, user_message))
        store.add_message(
            self.db,
            conversation.id,
            "system_internal",
            "",
            {"prompt_version": CEO_PROMPT_VERSION, "sources": context_sources, "context_chars": len(context_text)},
            correlation_id=correlation_id,
        )
        self.db.commit()

        totals = _Totals()
        specs = tool_specs()
        final = ""
        while True:
            response = self.provider.complete(
                ModelRequest(
                    system=system,
                    messages=messages,
                    tools=specs,
                    max_output_tokens=self.settings.ceo_chat_max_output_tokens,
                    timeout_seconds=self.settings.ceo_chat_timeout_seconds,
                    effort=self.settings.ceo_chat_effort,
                )
            )
            totals.add(response)
            # Antes que nada, el motivo de parada: una llamada a herramienta cortada por el límite puede estar truncada
            # y NO se ejecuta.
            if response.stop_reason == "max_tokens":
                totals.stopped = "max_output_tokens"
                partial = response.text.strip()
                final = f"{partial}\n\n{OUTPUT_LIMIT_NOTE}" if partial else OUTPUT_LIMIT_NOTE
                break
            if response.stop_reason == "refusal":
                totals.stopped = "refusal"
                final = MODEL_REFUSAL
                break
            if not response.tool_calls:
                final = response.text
                break
            if totals.tool_rounds >= self.settings.ceo_chat_max_tool_rounds:
                totals.stopped = "tool_rounds_exceeded"
                final = TOOL_ROUNDS_EXCEEDED
                break
            totals.tool_rounds += 1
            messages = [
                *messages,
                ModelMessage(
                    "assistant",
                    response.text,
                    tool_calls=response.tool_calls,
                    content_blocks=response.content_blocks,
                ),
            ]
            for call in response.tool_calls:
                content = self._run_tool(actor, conversation, call, totals, correlation_id)
                messages.append(ModelMessage("tool_result", content, tool_call_id=call.id))

        cost = self._cost(totals.input_tokens, totals.output_tokens)
        assistant = store.add_message(
            self.db,
            conversation.id,
            "assistant",
            final.strip() or "(sin respuesta)",
            None,
            provider=totals.provider,
            model=totals.model,
            prompt_version=CEO_PROMPT_VERSION,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            estimated_cost_usd=cost,
            external_cost_category=totals.cost_category,
            correlation_id=correlation_id,
        )
        for proposal in totals.proposals:
            proposal.message_id = assistant.id
        store.audit(
            self.db,
            actor,
            "ceo.response_generated",
            f"ceo_conversation:{conversation.id}",
            {
                "conversation_id": conversation.id,
                "message_id": assistant.id,
                "prompt_version": CEO_PROMPT_VERSION,
                "provider": totals.provider,
                "model": totals.model,
                "input_tokens": totals.input_tokens,
                "output_tokens": totals.output_tokens,
                "estimated_cost_usd": cost,
                "tool_rounds": totals.tool_rounds,
                "proposals": len(totals.proposals),
            },
            correlation_id,
        )
        conversation.updated_at = assistant.created_at
        self.db.commit()
        usage = {
            "rounds": totals.rounds,
            "tool_rounds": totals.tool_rounds,
            "input_tokens": totals.input_tokens,
            "output_tokens": totals.output_tokens,
            "estimated_cost_usd": cost,
            "provider": totals.provider,
            "model": totals.model,
            "external_cost_category": totals.cost_category,
            "stopped": totals.stopped,
        }
        return ChatTurn(
            conversation, user_message, assistant, totals.proposals, totals.sources, usage, totals.tool_messages
        )

    # --- Conversaciones
    # -------------------------------------------------------------------------------------------------------------

    def _conversation(self, actor: Actor, conversation_id: str | None, text: str) -> tuple[CeoConversation, bool]:
        if conversation_id is None:
            conversation = CeoConversation(owner_subject=actor.subject, title=redact_text(text)[:80])
            self.db.add(conversation)
            self.db.flush()
            return conversation, True
        return self._owned(actor, conversation_id), False

    def _owned(self, actor: Actor, conversation_id: str) -> CeoConversation:
        """De otro usuario es «no existe», no «prohibido»: no se confirma que exista."""
        conversation = self.db.get(CeoConversation, conversation_id)
        if conversation is None or conversation.owner_subject != actor.subject:
            raise NotFoundError(f"conversation {conversation_id} not found")
        return conversation

    def list_conversations(self, actor: Actor, limit: int = 50) -> list[CeoConversation]:
        return list(
            self.db.scalars(
                select(CeoConversation)
                .where(CeoConversation.owner_subject == actor.subject)
                .order_by(CeoConversation.updated_at.desc(), CeoConversation.id)
                .limit(limit)
            ).all()
        )

    def conversation_view(self, actor: Actor, conversation_id: str) -> dict[str, Any]:
        conversation = self._owned(actor, conversation_id)
        messages = self.db.scalars(
            select(CeoMessage)
            .where(CeoMessage.conversation_id == conversation.id, CeoMessage.role != "system_internal")
            .order_by(CeoMessage.seq)
        ).all()
        proposals = self.db.scalars(
            select(CeoActionProposal)
            .where(CeoActionProposal.conversation_id == conversation.id)
            .order_by(CeoActionProposal.created_at, CeoActionProposal.id)
        ).all()
        return {
            "id": conversation.id,
            "title": conversation.title,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            "messages": [message_view(m) for m in messages],
            "proposals": [proposal_view(p) for p in proposals],
        }

    # --- Historial y límites
    # --------------------------------------------------------------------------------------------------------

    def _history(self, conversation_id: str, current: CeoMessage) -> list[ModelMessage]:
        rows = self.db.scalars(
            select(CeoMessage)
            .where(
                CeoMessage.conversation_id == conversation_id,
                CeoMessage.role.in_(("user", "assistant")),
                CeoMessage.seq < current.seq,
            )
            .order_by(CeoMessage.seq.desc())
            .limit(self.settings.ceo_chat_history_messages)
        ).all()
        history = [ModelMessage(row.role, row.content) for row in reversed(rows)]  # type: ignore[arg-type]
        return [*history, ModelMessage("user", current.content)]

    def _fit(self, system: str, history: list[ModelMessage]) -> list[ModelMessage]:
        """Ajusta la petición al máximo de entrada: primero se descarta lo MÁS ANTIGUO del historial; si aún no cabe,
        se recorta el mensaje actual."""
        limit = self.settings.ceo_chat_max_input_chars

        def size(items: list[ModelMessage]) -> int:
            return len(system) + sum(len(m.content) for m in items)

        items = list(history)
        while len(items) > 1 and size(items) > limit:
            items.pop(0)
        while len(items) > 1 and items[0].role != "user":
            items.pop(0)
        if size(items) > limit:
            room = max(0, limit - len(system) - len(TRUNCATED))
            items[-1] = ModelMessage("user", items[-1].content[:room] + TRUNCATED)
        return items

    def _cost(self, input_tokens: int, output_tokens: int) -> float | None:
        """Estimado en dólares, o `None` si no hay tarifa configurada: nunca un cero inventado."""
        price_in, price_out = self.settings.ceo_chat_price_input_per_mtok, self.settings.ceo_chat_price_output_per_mtok
        if price_in is None or price_out is None:
            return None
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    # --- Herramientas
    # ---------------------------------------------------------------------------------------------------------------

    def _run_tool(
        self, actor: Actor, conversation: CeoConversation, call: ToolCall, totals: _Totals, correlation_id: str
    ) -> str:
        structured: dict[str, Any] = {
            "tool": call.name if isinstance(call.name, str) else "?",
            "call_id": call.id,
            "arguments": redact(call.arguments),
            "result": None,
            "error": None,
        }
        resource = f"ceo_conversation:{conversation.id}"
        base = {"conversation_id": conversation.id, "tool": structured["tool"]}
        try:
            arguments = parse_arguments(call.name, call.arguments)
            tool = TOOLS[call.name]
            if tool.kind == "propose" and len(totals.proposals) >= self.settings.ceo_chat_max_proposals_per_turn:
                raise ToolRejected(
                    f"too many proposals in one message: at most {self.settings.ceo_chat_max_proposals_per_turn}"
                )
            if tool.kind == "read":
                result = self._read(call.name, arguments)
                if SOURCE_LABELS[call.name] not in totals.sources:
                    totals.sources.append(SOURCE_LABELS[call.name])
                event_after = base
            else:
                proposal = self._propose(conversation, call.name, arguments, correlation_id)
                totals.proposals.append(proposal)
                result = {
                    "proposal_id": proposal.id,
                    "status": "PROPOSED",
                    "action_type": proposal.action_type,
                    "risk_level": proposal.risk_level,
                    "requires_confirmation": True,
                    "note": "Propuesta creada: NO se ha ejecutado nada. El propietario debe confirmarla en su tarjeta.",
                }
                event_after = {
                    **base,
                    "proposal_id": proposal.id,
                    "action_type": proposal.action_type,
                    "risk_level": proposal.risk_level,
                }
            structured["result"] = redact(result)
            store.audit(self.db, actor, tool.audit_event, resource, event_after, correlation_id)
        except ToolRejected as exc:
            structured["error"] = redact_text(str(exc))
            store.audit(
                self.db, actor, "ceo.tool_rejected", resource, {**base, "reason": structured["error"]}, correlation_id
            )
        except AmazonaError as exc:
            self.db.rollback()
            structured["error"] = redact_text(str(exc))
            store.audit(
                self.db, actor, "ceo.tool_failed", resource, {**base, "error_class": type(exc).__name__}, correlation_id
            )
        except Exception as exc:
            self.db.rollback()
            structured["error"] = "No disponible"
            store.audit(
                self.db, actor, "ceo.tool_failed", resource, {**base, "error_class": type(exc).__name__}, correlation_id
            )
        totals.tool_messages.append(
            store.add_message(self.db, conversation.id, "tool", "", structured, correlation_id=correlation_id)
        )
        self.db.commit()
        payload = {"result": structured["result"]} if structured["error"] is None else {"error": structured["error"]}
        content = json.dumps(payload, ensure_ascii=False, default=str)
        return content if len(content) <= MAX_TOOL_RESULT_CHARS else content[:MAX_TOOL_RESULT_CHARS] + TRUNCATED

    def _read(self, name: str, args: BaseModel) -> dict[str, Any]:
        db, manager = self.db, self.manager
        match name:
            case "get_system_status":
                return readers.read_system_status(db, manager)
            case "get_latest_mission":
                return readers.read_latest_mission(db, manager)
            case "get_budget_status":
                return readers.read_budget(db)
            case "get_pending_approvals":
                return readers.read_pending_approvals(db, include_resolved=args.include_resolved, limit=args.limit)  # type: ignore[attr-defined]
            case "get_task_details":
                return readers.read_task_details(db, manager, args.task_id)  # type: ignore[attr-defined]
            case "get_decision_history":
                return readers.read_decision_history(db, args.project_id)  # type: ignore[attr-defined]
            case "get_audit_summary":
                return readers.read_audit_summary(db, limit=args.limit, correlation_id=args.correlation_id)  # type: ignore[attr-defined]
        raise ToolRejected(f"unknown tool {name!r}: only the listed tools exist")

    def _propose(
        self, conversation: CeoConversation, name: str, args: BaseModel, correlation_id: str
    ) -> CeoActionProposal:
        db, manager = self.db, self.manager
        match name:
            case "propose_create_mission":
                draft = actions.draft_create_mission(args)  # type: ignore[arg-type]
            case "propose_retry_task":
                draft = actions.draft_retry_task(db, manager, args)  # type: ignore[arg-type]
            case "propose_reassign_task":
                draft = actions.draft_reassign_task(db, manager, args)  # type: ignore[arg-type]
            case "propose_resume_mission":
                draft = actions.draft_resume_mission(db, manager, args)  # type: ignore[arg-type]
            case "propose_resolve_approval":
                draft = actions.draft_resolve_approval(db, args)  # type: ignore[arg-type]
            case _:
                raise ToolRejected(f"unknown tool {name!r}: only the listed tools exist")
        assert name in PROPOSE_TOOLS
        proposal = CeoActionProposal(
            conversation_id=conversation.id,
            message_id=None,
            action_type=draft.action_type,
            target=redact(draft.target),
            parameters=redact(draft.parameters),
            reason=redact_text(draft.reason),
            estimated_effects=draft.estimated_effects,
            risk_level=draft.risk_level,
            requires_confirmation=True,
            idempotency_scope=draft.idempotency_scope,
            status="PROPOSED",
            correlation_id=correlation_id,
        )
        db.add(proposal)
        db.flush()
        return proposal
