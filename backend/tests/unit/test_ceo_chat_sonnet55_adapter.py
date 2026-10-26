"""El adaptador del CEO frente a Claude Sonnet 5.5 (M52C-A). Todo con `httpx.MockTransport`: ninguna red, ningún gasto.

Lo que cambia con Sonnet 5.5 y lo que el adaptador tiene que cumplir:

- el pensamiento va activado por defecto (adaptativo): una respuesta puede traer bloques `thinking` /
  `redacted_thinking` ANTES del texto o de un `tool_use`,
  así que no se puede suponer `content[0] == text`; el texto visible se compone SOLO de bloques `text`;
- al devolver un `tool_result`, esos bloques viajan de vuelta COMPLETOS, INALTERADOS y EN SU ORDEN con su turno del
  asistente (historial append-only);
- el esfuerzo (`output_config.effort`) es configurable con una lista cerrada; no se manda `thinking: disabled` (400 en
  este modelo) ni `tool_choice` forzado;
- que se agote `max_tokens` o que el modelo rehúse se detecta (`stop_reason`), no se presenta como una respuesta
  completa."""

import copy
import json

import httpx
import pytest
from pydantic import ValidationError as SettingsValidationError

from app.ceo_chat.provider import (
    AnthropicMessagesProvider,
    ModelMessage,
    ModelRequest,
    ToolCall,
)
from app.core.config import Settings

MODEL = "claude-sonnet-5-5"
THINKING = {"type": "thinking", "thinking": "RAZONAMIENTO-PRIVADO-XYZ", "signature": "sig/AAAA+bbbb==cccc"}
THINKING_OMITTED = {"type": "thinking", "thinking": "", "signature": "sig/OMITIDO+9876=="}
REDACTED = {"type": "redacted_thinking", "data": "EmwKAhgBEgy3va3pzix/LafPsn4aDFIT2Xlxh0L5L8rLVyIw=="}
TOOL_USE = {"type": "tool_use", "id": "toolu_01A", "name": "get_budget_status", "input": {}}
TEXT = {"type": "text", "text": "El presupuesto autorizado es de 2,00."}


def message(content: list[dict], *, stop_reason: str = "end_turn", usage: dict | None = None) -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "usage": usage or {"input_tokens": 120, "output_tokens": 30},
    }


class Recorder:
    """Un transporte simulado que responde en orden y apunta cada petición que recibe."""

    def __init__(self, *answers: dict | int) -> None:
        self.answers = list(answers)
        self.bodies: list[dict] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        answer = self.answers.pop(0)
        return httpx.Response(answer, json={}) if isinstance(answer, int) else httpx.Response(200, json=answer)

    def provider(self) -> AnthropicMessagesProvider:
        return AnthropicMessagesProvider(api_key="test-key-not-real", model=MODEL, client=self.client)


def request(messages: list[ModelMessage] | None = None, *, effort: str | None = "medium") -> ModelRequest:
    return ModelRequest(
        system="reglas",
        messages=messages or [ModelMessage(role="user", content="presupuesto")],
        tools=[],
        max_output_tokens=1024,
        timeout_seconds=5.0,
        effort=effort,
    )


# A / B / G. el texto visible sale SOLO de los bloques `text`, y nunca se asume `content[0]`


def test_A_a_text_only_answer_works():
    recorder = Recorder(message([TEXT]))

    response = recorder.provider().complete(request())

    assert response.text == TEXT["text"] and response.tool_calls == () and response.stop_reason == "end_turn"
    assert response.content_blocks == (TEXT,)


def test_B_thinking_plus_text_shows_only_the_text():
    recorder = Recorder(message([THINKING, TEXT]))

    response = recorder.provider().complete(request())

    assert response.text == TEXT["text"]
    assert "RAZONAMIENTO-PRIVADO-XYZ" not in response.text and "sig/" not in response.text


def test_G_content_zero_being_thinking_does_not_break_the_parser():
    recorder = Recorder(message([THINKING_OMITTED, REDACTED, TEXT]))

    response = recorder.provider().complete(request())

    assert response.text == TEXT["text"]
    assert response.content_blocks == (THINKING_OMITTED, REDACTED, TEXT)


def test_blocks_of_a_kind_the_adapter_does_not_know_are_kept_but_never_shown():
    unknown = {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "x"}}
    recorder = Recorder(message([unknown, TEXT]))

    response = recorder.provider().complete(request())

    assert response.text == TEXT["text"] and response.content_blocks == (unknown, TEXT)


def test_an_answer_without_a_content_list_is_an_unreadable_answer_not_a_crash():
    from app.ceo_chat.provider import ModelUnavailableError

    recorder = Recorder({"id": "m", "content": "no es una lista", "stop_reason": "end_turn", "usage": {}})

    with pytest.raises(ModelUnavailableError, match="unreadable"):
        recorder.provider().complete(request())


# C / D / E / F / H. el bucle de herramientas devuelve los bloques tal cual


def two_rounds(first_content: list[dict]) -> tuple[Recorder, dict, dict]:
    """Ronda 1 (el modelo pide una herramienta) y ronda 2 (la respuesta final), con el `tool_result` en medio."""
    recorder = Recorder(message(first_content, stop_reason="tool_use"), message([THINKING_OMITTED, TEXT]))
    provider = recorder.provider()
    first = provider.complete(request())
    history = [
        ModelMessage(role="user", content="presupuesto"),
        ModelMessage(
            role="assistant", content=first.text, tool_calls=first.tool_calls, content_blocks=first.content_blocks
        ),
        ModelMessage(role="tool_result", content='{"hard_limit": "2.00"}', tool_call_id="toolu_01A"),
    ]
    provider.complete(request(history))
    return recorder, recorder.bodies[0], recorder.bodies[1]


def test_C_thinking_plus_tool_use_sends_the_thinking_back_with_the_tool_result():
    _, first, second = two_rounds([THINKING, TOOL_USE])

    assistant = second["messages"][1]
    assert assistant["role"] == "assistant" and assistant["content"] == [THINKING, TOOL_USE]
    result = second["messages"][2]
    assert result["role"] == "user" and result["content"][0]["type"] == "tool_result"
    assert result["content"][0]["tool_use_id"] == "toolu_01A"


def test_D_redacted_thinking_plus_tool_use_is_preserved_intact():
    _, _, second = two_rounds([REDACTED, TOOL_USE])

    assert second["messages"][1]["content"] == [REDACTED, TOOL_USE]
    assert second["messages"][1]["content"][0]["data"] == REDACTED["data"]


def test_E_the_signature_is_never_changed():
    original = copy.deepcopy(THINKING)

    _, _, second = two_rounds([THINKING, TOOL_USE])

    assert second["messages"][1]["content"][0]["signature"] == original["signature"] == "sig/AAAA+bbbb==cccc"
    assert second["messages"][1]["content"][0] == original  # ni la firma, ni el texto, ni ningún campo


def test_F_the_order_of_the_blocks_is_kept():
    second_tool = {"type": "tool_use", "id": "toolu_02B", "name": "get_system_status", "input": {}}
    _, _, second = two_rounds([THINKING, TEXT, second_tool, TOOL_USE])

    assert [block["type"] for block in second["messages"][1]["content"]] == ["thinking", "text", "tool_use", "tool_use"]
    assert [b.get("id") for b in second["messages"][1]["content"] if b["type"] == "tool_use"] == [
        "toolu_02B",
        "toolu_01A",
    ]


def test_H_the_second_round_is_append_only_over_the_first():
    _, first, second = two_rounds([THINKING, TOOL_USE])

    assert second["system"] == first["system"] and second.get("tools") == first.get("tools")
    assert second["messages"][: len(first["messages"])] == first["messages"]  # lo anterior no cambia
    assert (
        len(second["messages"]) == len(first["messages"]) + 2
    )  # solo se añade el turno del asistente y los resultados


def test_without_raw_blocks_the_assistant_turn_is_rebuilt_as_before():
    """Un proveedor que no devuelve bloques crudos (el modelo falso de las pruebas) sigue funcionando como antes."""
    recorder = Recorder(message([TEXT]))
    messages = [
        ModelMessage(role="user", content="q"),
        ModelMessage(role="assistant", content="miro", tool_calls=(ToolCall("toolu_01A", "get_budget_status", {}),)),
        ModelMessage(role="tool_result", content="{}", tool_call_id="toolu_01A"),
    ]

    recorder.provider().complete(request(messages))

    assert recorder.bodies[0]["messages"][1]["content"] == [{"type": "text", "text": "miro"}, TOOL_USE]


# I. el esfuerzo y lo que NO se manda


def test_I_the_effort_is_sent_as_output_config():
    recorder = Recorder(message([TEXT]))

    recorder.provider().complete(request(effort="medium"))

    assert recorder.bodies[0]["output_config"] == {"effort": "medium"}
    assert recorder.bodies[0]["max_tokens"] == 1024 and recorder.bodies[0]["model"] == MODEL


def test_no_effort_means_no_output_config():
    recorder = Recorder(message([TEXT]))

    recorder.provider().complete(request(effort=None))

    assert "output_config" not in recorder.bodies[0]


def test_thinking_is_never_disabled_and_nothing_incompatible_is_sent():
    recorder = Recorder(message([TEXT]))

    recorder.provider().complete(request())

    body = recorder.bodies[0]
    for forbidden in ("thinking", "tool_choice", "temperature", "top_p", "top_k", "budget_tokens"):
        assert forbidden not in body, forbidden
    assert "disabled" not in json.dumps(body)


# M. el límite de salida y el rechazo se ven en `stop_reason`


@pytest.mark.parametrize("reason", ["max_tokens", "refusal", "tool_use", "end_turn"])
def test_M_the_stop_reason_reaches_the_caller(reason):
    recorder = Recorder(message([THINKING_OMITTED], stop_reason=reason))

    response = recorder.provider().complete(request())

    assert response.stop_reason == reason and response.text == ""


# J / K / L. el esfuerzo de la configuración


def test_the_default_effort_is_medium():
    assert Settings(_env_file=None).ceo_chat_effort == "medium"


@pytest.mark.parametrize("value", ["low", "medium", "high"])
def test_J_K_the_three_levels_are_accepted(value):
    assert Settings(_env_file=None, ceo_chat_effort=value).ceo_chat_effort == value


@pytest.mark.parametrize("value", ["xhigh", "max", "LOW", "", "banana", "disabled", "none"])
def test_L_any_other_value_fails_the_configuration(value):
    with pytest.raises(SettingsValidationError):
        Settings(_env_file=None, ceo_chat_effort=value)


def test_L_the_environment_variable_is_validated_too(monkeypatch):
    monkeypatch.setenv("CEO_CHAT_EFFORT", "banana")

    with pytest.raises(SettingsValidationError):
        Settings(_env_file=None)

    monkeypatch.setenv("CEO_CHAT_EFFORT", "high")
    assert Settings(_env_file=None).ceo_chat_effort == "high"
