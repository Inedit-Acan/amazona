"""Apoyo de las pruebas del chat con el CEO (M52). Módulo auxiliar, NO un test.

`ScriptedProvider` es un modelo FALSO: cumple `CEOModelProvider` y responde lo que el guion diga (texto, llamadas a
herramientas o un fallo). Así se prueba
todo el dominio del chat —herramientas, propuestas, confirmación, persistencia, auditoría— sin llamar a ningún modelo
real ni gastar nada."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.auth.actor import Actor, ActorSource, RoleName
from app.ceo_chat.provider import ModelRequest, ModelResponse, ToolCall, Usage

OWNER = Actor(subject="owner-sub-1", email="owner@example.com", role=RoleName.OWNER, source=ActorSource.TOKEN)
OTHER_OWNER = Actor(subject="owner-sub-2", email="other@example.com", role=RoleName.OWNER, source=ActorSource.TOKEN)


def say(text: str, *, input_tokens: int = 100, output_tokens: int = 20) -> ModelResponse:
    return ModelResponse(text, (), Usage(input_tokens, output_tokens), "scripted", "scripted-1", "end_turn")


def call(
    *calls: tuple[str, dict[str, Any]], text: str = "", input_tokens: int = 100, output_tokens: int = 20
) -> ModelResponse:
    tool_calls = tuple(
        ToolCall(id=f"call_{index}", name=name, arguments=args) for index, (name, args) in enumerate(calls, start=1)
    )
    return ModelResponse(text, tool_calls, Usage(input_tokens, output_tokens), "scripted", "scripted-1", "tool_use")


Step = ModelResponse | Exception | Callable[[ModelRequest], ModelResponse]


@dataclass
class ScriptedProvider:
    """Responde en orden lo que se le diga. Un paso puede ser una respuesta, una excepción (el proveedor cae) o una
    función de la petición."""

    steps: list[Step]
    name: str = "scripted"
    model: str = "scripted-1"
    requests: list[ModelRequest] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError("the scripted provider was called more times than the script allows")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(request)
        return step


def always_calls(name: str, arguments: dict[str, Any]) -> Callable[[ModelRequest], ModelResponse]:
    """Un modelo que pide la misma herramienta sin parar (para probar el tope de rondas)."""
    return lambda request: call((name, arguments))
