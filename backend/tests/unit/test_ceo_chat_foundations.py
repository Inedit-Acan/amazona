"""Cimientos del chat con el CEO (M52): redacción, prompt versionado, contrato de herramientas y adaptador del
proveedor.

Nada de esto llama a un modelo: el adaptador del proveedor se prueba contra un transporte HTTP simulado
(`httpx.MockTransport`), que no sale de la
máquina. La seguridad del chat descansa en tres cosas que se prueban aquí: lo que ve el modelo se REDACTA, el modelo
solo puede pedir herramientas de
una lista CERRADA y TIPADA, y no existe ninguna herramienta que confirme una acción."""

import hashlib
import json

import httpx
import pytest
from pydantic import BaseModel

from app.ceo_chat.prompt import CEO_PROMPT_VERSION, CEO_SYSTEM_PROMPT, CONTEXT_HEADER, system_prompt
from app.ceo_chat.provider import (
    AnthropicMessagesProvider,
    ModelMessage,
    ModelRequest,
    ModelToolSpec,
    ModelUnavailableError,
    ToolCall,
)
from app.ceo_chat.redaction import REDACTED, redact, redact_text
from app.ceo_chat.tools import PROPOSE_TOOLS, READ_TOOLS, TOOLS, ToolRejected, parse_arguments, tool_specs

# --- Redacción
# ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "forbidden"),
    [
        ("contacta con ivan@example.com ahora", "ivan@example.com"),
        ("token eyJhbGciOiJSUzI1NiIsImtpZCI6IjEifQ.eyJzdWIiOiJ4In0.c2lnbmF0dXJl listo", "eyJhbGciOiJSUzI1NiIs"),
        ("clave sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx", "sk-ant-api03"),
        ("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
        ("postgresql+psycopg://postgres:SuperSecreta@db.example.com:5432/postgres", "SuperSecreta"),
        ("password=hunter2 y api_key: abc123def456", "hunter2"),
        ("service_role_key = eyJabc.def.ghi", "eyJabc"),
    ],
)
def test_secrets_never_survive_redaction(text, forbidden):
    assert forbidden not in redact_text(text)


def test_redaction_keeps_what_is_not_secret():
    text = "Misión 5f62bc28-24de-46d5-9d5c-a0130e5f3b99: 5 tareas, presupuesto 2,00 EUR, estado GO"
    assert redact_text(text) == text


def test_redaction_walks_structures_and_hides_sensitive_keys():
    data = {
        "password": "x",
        "access_token": "y",
        "nested": {"api_key": "z", "ok": "valor", "mail": "a@b.com"},
        "lista": [{"Authorization": "Bearer q"}, "sin problema"],
        "n": 3,
    }
    out = redact(data)
    assert out["password"] == out["access_token"] == out["nested"]["api_key"] == REDACTED
    assert out["lista"][0]["Authorization"] == REDACTED
    assert out["nested"]["ok"] == "valor" and out["lista"][1] == "sin problema" and out["n"] == 3
    assert "a@b.com" not in json.dumps(out)


def test_redaction_does_not_mutate_its_input():
    data = {"password": "x"}
    redact(data)
    assert data == {"password": "x"}


# --- Prompt versionado
# ------------------------------------------------------------------------------------------------------------------

#: Si el texto del prompt cambia, este hash y `CEO_PROMPT_VERSION` cambian a la vez: un cambio de prompt nunca pasa
#: desapercibido.
PROMPT_SHA256 = "64051a2df8692e5c86a8844e00c94bb4208439eaef629f58ae9595a120355889"


def test_the_prompt_is_versioned_and_its_text_is_pinned():
    assert CEO_PROMPT_VERSION == "ceo-chat-1"
    assert hashlib.sha256(CEO_SYSTEM_PROMPT.encode("utf-8")).hexdigest() == PROMPT_SHA256


@pytest.mark.parametrize(
    "clause",
    [
        "orquestador",
        "datos reales",
        "hecho",
        "inferencia",
        "No inventes",
        "No afirmes",
        "confirmación",
        "No reveles",
        "presupuesto",
        "permisos",
    ],
)
def test_the_prompt_states_every_rule(clause):
    assert clause in CEO_SYSTEM_PROMPT


def test_the_context_goes_after_the_rules_and_is_labelled_as_data():
    text = system_prompt('{"presupuesto": 2}')
    assert text.startswith(CEO_SYSTEM_PROMPT)
    assert text.index(CONTEXT_HEADER) >= len(CEO_SYSTEM_PROMPT)
    assert text.rstrip().endswith('{"presupuesto": 2}')


# --- Contrato de herramientas
# -----------------------------------------------------------------------------------------------------------


def test_the_tool_list_is_closed_and_exact():
    assert set(READ_TOOLS) == {
        "get_system_status",
        "get_latest_mission",
        "get_budget_status",
        "get_pending_approvals",
        "get_task_details",
        "get_decision_history",
        "get_audit_summary",
    }
    assert set(PROPOSE_TOOLS) == {
        "propose_create_mission",
        "propose_retry_task",
        "propose_reassign_task",
        "propose_resume_mission",
        "propose_resolve_approval",
    }
    assert set(TOOLS) == set(READ_TOOLS) | set(PROPOSE_TOOLS)


def test_no_tool_can_confirm_an_action_run_sql_or_touch_files():
    for name in TOOLS:
        assert not any(
            word in name for word in ("confirm", "execute", "sql", "shell", "file", "env", "exec", "git", "pay")
        )


def test_every_tool_declares_the_whole_contract():
    for name, tool in TOOLS.items():
        assert tool.name == name
        assert tool.description.strip()
        assert issubclass(tool.input_model, BaseModel)
        assert tool.output_schema
        assert tool.permission == "OWNER"
        assert tool.audit_event in {"ceo.tool_read", "ceo.action_proposed"}


def test_read_tools_have_no_effects_and_propose_tools_only_propose():
    for tool in READ_TOOLS.values():
        assert (tool.side_effects, tool.confirmation_required) == ("none", False)
        assert tool.audit_event == "ceo.tool_read"
    for tool in PROPOSE_TOOLS.values():
        assert (tool.side_effects, tool.confirmation_required) == ("proposal_only", True)
        assert tool.audit_event == "ceo.action_proposed"


def test_every_input_model_forbids_extra_fields():
    for tool in TOOLS.values():
        assert tool.input_model.model_config.get("extra") == "forbid", tool.name


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("run_sql", {"query": "select 1"}),
        ("read_file", {"path": ".env"}),
        ("confirm_action", {"proposal_id": "x"}),
        ("", {}),
        ("get_budget_status", {"extra": 1}),
        ("get_task_details", {}),
        ("get_task_details", {"task_id": 5}),
        ("get_pending_approvals", {"limit": 99}),
        ("get_pending_approvals", {"limit": "5"}),
        ("propose_retry_task", {"task_id": "t-1", "after_attempt": 0, "reason": "abc"}),
        ("propose_reassign_task", {"task_id": "t-1", "agent_id": "a", "reason": "x"}),
        ("propose_resolve_approval", {"approval_id": "a-1", "decision": "maybe", "reason": "abc"}),
    ],
)
def test_an_invented_tool_or_bad_arguments_are_rejected(name, arguments):
    with pytest.raises(ToolRejected):
        parse_arguments(name, arguments)


def test_valid_arguments_parse():
    parsed = parse_arguments("get_pending_approvals", {"limit": 3})
    assert parsed.limit == 3
    assert parse_arguments("get_budget_status", {}) is not None
    parsed = parse_arguments(
        "propose_resolve_approval", {"approval_id": "a-1", "decision": "reject", "reason": "no procede"}
    )
    assert parsed.decision == "reject"


def test_a_mission_proposal_cannot_ask_for_spend():
    for forbidden in ("requests_simulated_spend", "spend_amount", "spend_action"):
        for section in (1, {"amount": 1}):  # ni suelto ni dentro de una sección: la clave en sí no está permitida
            with pytest.raises(ToolRejected, match="invalid arguments"):
                parse_arguments(
                    "propose_create_mission",
                    {"title": "Investigar X", "reason": "analisis", "context": {forbidden: section}},
                )
    ok = parse_arguments(
        "propose_create_mission",
        {
            "title": "Investigar X",
            "reason": "analisis",
            "context": {"product_validation": {"competition_level": "low"}},
        },
    )
    assert ok.title == "Investigar X"


def test_tool_specs_expose_a_json_schema_for_the_provider():
    specs = tool_specs()
    assert {spec.name for spec in specs} == set(TOOLS)
    for spec in specs:
        assert spec.input_schema["type"] == "object"
        assert spec.input_schema.get("additionalProperties") is False


# --- Adaptador del proveedor (transporte simulado, sin red)
# -----------------------------------------------------------------------------


def make_provider(handler, **over):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AnthropicMessagesProvider(api_key="k-test", model="modelo-x", client=client, **over)


def request(**over):
    base = {
        "system": "reglas",
        "messages": [ModelMessage(role="user", content="hola")],
        "tools": [
            ModelToolSpec(name="get_budget_status", description="d", input_schema={"type": "object", "properties": {}})
        ],
        "max_output_tokens": 256,
        "timeout_seconds": 5.0,
    }
    base.update(over)
    return ModelRequest(**base)


def test_the_request_is_built_for_the_messages_api_and_the_key_goes_in_a_header_only():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )

    response = make_provider(handler).complete(request())

    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "k-test" and seen["headers"]["anthropic-version"]
    assert "k-test" not in json.dumps(seen["body"])
    assert (
        seen["body"]["model"] == "modelo-x" and seen["body"]["max_tokens"] == 256 and seen["body"]["system"] == "reglas"
    )
    assert seen["body"]["tools"][0]["name"] == "get_budget_status"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hola"}]
    assert (response.text, response.usage.input_tokens, response.usage.output_tokens) == ("ok", 10, 4)
    assert (response.provider, response.model, response.tool_calls) == ("anthropic", "modelo-x", ())


def test_tool_use_blocks_become_tool_calls():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "miro el presupuesto"},
                    {"type": "tool_use", "id": "tu_1", "name": "get_budget_status", "input": {}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    response = make_provider(handler).complete(request())

    assert response.text == "miro el presupuesto"
    assert response.tool_calls == (ToolCall(id="tu_1", name="get_budget_status", arguments={}),)


def test_tool_results_go_back_as_one_user_message_with_tool_result_blocks():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "fin"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        )

    messages = [
        ModelMessage(role="user", content="presupuesto?"),
        ModelMessage(
            role="assistant",
            content="lo miro",
            tool_calls=(ToolCall(id="tu_1", name="get_budget_status", arguments={}),),
        ),
        ModelMessage(role="tool_result", content='{"hard_limit": "2.00"}', tool_call_id="tu_1"),
    ]
    make_provider(handler).complete(request(messages=messages))

    wire = seen["body"]["messages"]
    assert wire[1]["role"] == "assistant" and wire[1]["content"][-1] == {
        "type": "tool_use",
        "id": "tu_1",
        "name": "get_budget_status",
        "input": {},
    }
    assert wire[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": '{"hard_limit": "2.00"}'}],
    }


@pytest.mark.parametrize("status", [400, 401, 429, 500, 529])
def test_an_error_status_is_a_controlled_unavailable_error_that_never_echoes_the_key(status):
    def handler(req):
        return httpx.Response(status, json={"error": {"message": "mala clave k-test"}})

    with pytest.raises(ModelUnavailableError) as raised:
        make_provider(handler).complete(request())
    assert "k-test" not in str(raised.value)


def test_a_timeout_or_a_network_error_is_a_controlled_unavailable_error():
    def timeout(req):
        raise httpx.ReadTimeout("lento", request=req)

    def network(req):
        raise httpx.ConnectError("sin red", request=req)

    for handler in (timeout, network):
        with pytest.raises(ModelUnavailableError):
            make_provider(handler).complete(request())


def test_a_malformed_answer_is_a_controlled_unavailable_error():
    def handler(req):
        return httpx.Response(200, json={"nada": True})

    with pytest.raises(ModelUnavailableError):
        make_provider(handler).complete(request())


def test_the_adapter_refuses_to_exist_without_key_or_model():
    with pytest.raises(ModelUnavailableError):
        AnthropicMessagesProvider(api_key="", model="m")
    with pytest.raises(ModelUnavailableError):
        AnthropicMessagesProvider(api_key="k", model=" ")
