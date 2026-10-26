"""El contrato con el modelo de lenguaje del CEO (M52) y su ÚNICA implementación inicial.

El dominio del chat depende de `CEOModelProvider`, nunca de un SDK ni de un proveedor concreto: cambiar de Claude a
otro modelo es escribir otra clase que
cumpla el protocolo, sin tocar el servicio, las herramientas ni la interfaz. (`app/ai/gateway.py` es otra cosa: la
pasarela de las llamadas ESTRUCTURADAS de los
agentes; un chat con herramientas necesita mensajes, llamadas a herramientas y uso en tokens.)

Implementación inicial: `AnthropicMessagesProvider`, sobre la API de mensajes de Anthropic por HTTP (`httpx`, que ya es
una dependencia de producción). No hay
modelo por defecto ni clave por defecto: sin ambas el adaptador no se construye y el chat dice «no disponible». Aquí no
se llama a ninguna red en las
pruebas: se usa un transporte simulado.

Ninguna excepción de este módulo lleva la clave ni el cuerpo de la respuesta del proveedor: un fallo es siempre un
`ModelUnavailableError` con un texto fijo.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.core.errors import AmazonaError

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class ModelUnavailableError(AmazonaError):
    """El modelo no puede responder ahora (sin configurar, sin red, tiempo agotado, error del proveedor, respuesta
    ilegible). El chat lo muestra como
    «no disponible»; nunca ejecuta nada por ello."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ModelMessage:
    """`user`, `assistant` (con las herramientas que pidió, si pidió) o `tool_result` (la salida de una herramienta, ya
    redactada)."""

    role: Literal["user", "assistant", "tool_result"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    #: Los bloques del turno del asistente EXACTAMENTE como los devolvió el modelo (`thinking`, `redacted_thinking`,
    #: `text`, `tool_use`…), en su orden. Solo viven en memoria durante el ciclo de herramientas: al devolver un
    #: `tool_result` el modelo necesita ver su razonamiento tal cual (con su firma). Nunca se guardan ni se enseñan.
    content_blocks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ModelRequest:
    system: str
    messages: list[ModelMessage]
    tools: list[ModelToolSpec]
    max_output_tokens: int
    timeout_seconds: float
    #: `low` / `medium` / `high`, o `None` para no mandarlo.
    effort: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    provider: str
    model: str
    stop_reason: str | None = None
    #: Los bloques de la respuesta tal cual llegaron (ver `ModelMessage.content_blocks`). Vacío en un proveedor que no
    #: los tiene.
    content_blocks: tuple[dict[str, Any], ...] = ()
    #: De dónde sale el coste de esta consulta (categoría de gasto de IA, separada del gasto comercial y del cash).
    cost_category: str = "claude_credits"
    extra: dict[str, Any] = field(default_factory=dict)


class CEOModelProvider(Protocol):
    name: str
    model: str

    def complete(self, request: ModelRequest) -> ModelResponse: ...


def _to_wire(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush() -> None:
        if pending:
            wire.append({"role": "user", "content": list(pending)})
            pending.clear()

    for message in messages:
        if message.role == "tool_result":
            pending.append({"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content})
            continue
        flush()
        if message.role == "assistant" and message.tool_calls and message.content_blocks:
            # Los bloques del modelo, completos, inalterados y en su orden: nada se resume, se reescribe ni se reordena.
            wire.append({"role": "assistant", "content": copy.deepcopy(list(message.content_blocks))})
        elif message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                for call in message.tool_calls
            )
            wire.append({"role": "assistant", "content": blocks})
        else:
            wire.append({"role": message.role, "content": message.content})
    flush()
    return wire


class AnthropicMessagesProvider:
    name = "anthropic"

    def __init__(
        self, *, api_key: str, model: str, base_url: str = ANTHROPIC_BASE_URL, client: httpx.Client | None = None
    ) -> None:
        if not api_key or not api_key.strip():
            raise ModelUnavailableError("the model provider has no API key configured")
        if not model or not model.strip():
            raise ModelUnavailableError("the model provider has no model configured")
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client()

    def complete(self, request: ModelRequest) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": _to_wire(request.messages),
        }
        if request.effort:
            body["output_config"] = {"effort": request.effort}
        if request.tools:
            body["tools"] = [
                {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                for tool in request.tools
            ]
        try:
            response = self._client.post(
                f"{self._base_url}/v1/messages",
                json=body,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException:
            raise ModelUnavailableError("the model provider did not answer in time") from None
        except httpx.HTTPError:
            raise ModelUnavailableError("the model provider could not be reached") from None
        if response.status_code >= 400:
            raise ModelUnavailableError(f"the model provider answered with status {response.status_code}")
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> ModelResponse:
        try:
            data = response.json()
            blocks = data["content"]
            if not isinstance(blocks, list):
                raise ValueError("content is not a list")
            usage = data.get("usage") or {}
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            raw: list[dict[str, Any]] = []
            for block in blocks:
                # Por `type`, nunca por posición: con el pensamiento activado el primer bloque suele ser un `thinking`.
                # El texto visible sale SOLO de los bloques `text`; todo bloque se conserva tal cual para el ciclo de
                # herramientas.
                raw.append(copy.deepcopy(block))
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_use":
                    arguments = block.get("input") or {}
                    if not isinstance(arguments, dict):
                        raise ValueError("tool input is not an object")
                    calls.append(ToolCall(id=str(block["id"]), name=str(block["name"]), arguments=arguments))
            return ModelResponse(
                text="".join(text_parts),
                tool_calls=tuple(calls),
                usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))),
                provider=self.name,
                model=self.model,
                stop_reason=data.get("stop_reason"),
                content_blocks=tuple(raw),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ModelUnavailableError("the model provider returned an unreadable answer") from None
