"""La conversación escrita con el CEO (M52).

    POST /api/ceo/chat                              un mensaje del propietario → la respuesta del CEO (con lo que leyó
    y lo que PROPONE)
    GET  /api/ceo/conversations                     sus conversaciones
    GET  /api/ceo/conversations/{id}                una conversación entera (nunca `system_internal`)
    POST /api/ceo/actions/{id}/confirm              el propietario CONFIRMA una propuesta → se ejecuta (Idempotency-Key
    obligatoria)
    POST /api/ceo/actions/{id}/reject               el propietario la RECHAZA → no se ejecuta nada

Solo el propietario: una identidad VERIFICADA (token) con rol OWNER, también en desarrollo. Sin token es un 401; con
otro rol, 403 (ADMIN incluido: `authorize`
le da todas las acciones y aquí se exige OWNER de forma explícita). Si el modelo no está disponible la respuesta es un
503 CONTROLADO, con la conversación a
salvo: el resto del panel no depende de este endpoint.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.manager import AgentManager
from app.api.tasks import get_agent_manager
from app.auth.actor import Actor, RoleName
from app.auth.dependencies import authorize
from app.ceo_chat.actions import ActionService, Outcome
from app.ceo_chat.provider import AnthropicMessagesProvider, CEOModelProvider, ModelUnavailableError
from app.ceo_chat.service import CEOChatService, ChatTurn, ChatUnavailableError, message_view, proposal_view
from app.core.config import Settings, get_settings
from app.db.models.ceo_chat import CeoMessage
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/ceo", tags=["ceo-chat"])


def authorize_owner(actor: Actor = Depends(authorize(ApiAction.CEO_CHAT))) -> Actor:
    """Una identidad verificada con rol OWNER. En desarrollo `authorize` no hace cumplir roles, así que aquí se
    comprueba SIEMPRE."""
    if not actor.is_verified:
        raise HTTPException(status_code=401, detail="the CEO chat requires a verified identity")
    if actor.role is not RoleName.OWNER:
        raise HTTPException(status_code=403, detail=f"role {actor.role or 'none'} is not allowed to talk to the CEO")
    return actor


_providers: dict[tuple[str, str, str], CEOModelProvider] = {}


def get_chat_provider(settings: Settings = Depends(get_settings)) -> CEOModelProvider | None:
    """El proveedor del modelo, o `None` si no hay uno configurado (el chat dice «no disponible»; no se llama a ninguna
    red). Una dependencia para que
    las pruebas sustituyan el modelo por uno falso."""
    if not settings.ceo_chat_available or settings.anthropic_api_key is None:
        return None
    key = settings.anthropic_api_key.get_secret_value()
    cache_key = (settings.ceo_chat_provider, settings.ceo_chat_model, key)
    if cache_key not in _providers:
        _providers[cache_key] = AnthropicMessagesProvider(api_key=key, model=settings.ceo_chat_model)
    return _providers[cache_key]


# --- Esquemas
# ----------------------------------------------------------------------------------------------------


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=36)


class ChatOut(BaseModel):
    conversation_id: str
    user_message: dict[str, Any]
    #: Lo que el CEO leyó o intentó para responder, en orden (cada una con su salida estructurada).
    tool_messages: list[dict[str, Any]]
    assistant_message: dict[str, Any]
    #: Las acciones que PROPONE. Ninguna está ejecutada: cada una espera la confirmación del propietario.
    proposals: list[dict[str, Any]]
    sources: list[str]
    #: Tokens, coste estimado de la consulta (`null` sin tarifa) y su categoría. Gasto de IA: no es gasto comercial ni
    #: cash.
    usage: dict[str, Any]


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    created_at: str | None
    updated_at: str | None


class ConversationOut(ConversationSummary):
    messages: list[dict[str, Any]]
    proposals: list[dict[str, Any]]


class ActionOut(BaseModel):
    proposal: dict[str, Any]
    #: El mensaje que da cuenta del resultado (ejecutado, fallido o rechazado).
    result_message: dict[str, Any] | None


def _turn_out(turn: ChatTurn) -> ChatOut:
    return ChatOut(
        conversation_id=turn.conversation.id,
        user_message=message_view(turn.user_message),
        tool_messages=[message_view(m) for m in turn.tool_messages],
        assistant_message=message_view(turn.assistant_message),
        proposals=[proposal_view(p) for p in turn.proposals],
        sources=turn.sources,
        usage=turn.usage,
    )


def _action_out(db: Session, outcome: Outcome) -> ActionOut:
    message = db.get(CeoMessage, outcome.result_message_id) if outcome.result_message_id else None
    return ActionOut(
        proposal=proposal_view(outcome.proposal), result_message=message_view(message) if message else None
    )


# --- Rutas
# ----------------------------------------------------------------------------------------------------


@router.post("/chat", response_model=ChatOut)
def chat(
    payload: ChatIn,
    response: Response,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    provider: CEOModelProvider | None = Depends(get_chat_provider),
    identity: Actor = Depends(authorize_owner),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ChatOut:
    """Un mensaje del propietario y la respuesta del CEO. Con `Idempotency-Key`, repetir la petición devuelve la misma
    respuesta sin volver a llamar al
    modelo (ni a gastar). 503 si el modelo no está disponible: el mensaje queda guardado y la conversación es la que
    dice `detail.conversation_id`."""
    service = CEOChatService(db, provider=provider, manager=manager, settings=settings)

    def work() -> ChatOut:
        try:
            return _turn_out(
                service.chat(actor=identity, text=payload.message, conversation_id=payload.conversation_id)
            )
        except ChatUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "model_unavailable",
                    "message": (
                        "El CEO no está disponible ahora. Tu mensaje se ha guardado; "
                        "el resto del panel sigue funcionando."
                    ),
                    "conversation_id": exc.conversation_id,
                },
            ) from exc
        except ModelUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "model_unavailable",
                    "message": "El CEO no está disponible ahora.",
                    "conversation_id": payload.conversation_id,
                },
            ) from exc

    return run_idempotent(
        db,
        scope="ceo.chat",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload=payload.model_dump(),
        response=response,
        status_code=200,
        response_model=ChatOut,
        work=work,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    provider: CEOModelProvider | None = Depends(get_chat_provider),
    identity: Actor = Depends(authorize_owner),
    settings: Settings = Depends(get_settings),
) -> list[ConversationSummary]:
    service = CEOChatService(db, provider=provider, manager=manager, settings=settings)
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            created_at=c.created_at.isoformat() if c.created_at else None,
            updated_at=c.updated_at.isoformat() if c.updated_at else None,
        )
        for c in service.list_conversations(identity)
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    provider: CEOModelProvider | None = Depends(get_chat_provider),
    identity: Actor = Depends(authorize_owner),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return CEOChatService(db, provider=provider, manager=manager, settings=settings).conversation_view(
        identity, conversation_id
    )


@router.post("/actions/{proposal_id}/confirm", response_model=ActionOut)
def confirm_action(
    proposal_id: str,
    response: Response,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    identity: Actor = Depends(authorize_owner),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> ActionOut:
    """El propietario CONFIRMA una propuesta: se re-valida y se ejecuta con los mismos servicios que las rutas de
    siempre. Idempotency-Key obligatoria
    (también en una simulación). Repetirla con la misma clave devuelve lo mismo sin ejecutar otra vez; con otra clave,
    409: una propuesta se resuelve una vez.
    200 aunque la acción ya no sea posible (otra persona se adelantó): la propuesta queda `FAILED` y el cuerpo lo
    dice."""
    service = ActionService(db, manager, settings)
    proposal = service.get_owned(identity, proposal_id)  # 404 si no es suya, antes de reclamar la clave

    def work() -> ActionOut:
        return _action_out(db, service.confirm(identity, proposal_id))

    return run_idempotent(
        db,
        scope=proposal.idempotency_scope or "approvals.resolve",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"via": "ceo_chat", "proposal_id": proposal_id, "decision": "confirm"},
        response=response,
        status_code=200,
        response_model=ActionOut,
        work=work,
        always_required=True,
    )


@router.post("/actions/{proposal_id}/reject", response_model=ActionOut)
def reject_action(
    proposal_id: str,
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_agent_manager),
    identity: Actor = Depends(authorize_owner),
    settings: Settings = Depends(get_settings),
) -> ActionOut:
    """El propietario RECHAZA una propuesta: no se ejecuta nada. Transición con compare-and-set: repetirla es un 409."""
    return _action_out(db, ActionService(db, manager, settings).reject(identity, proposal_id))
