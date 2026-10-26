"""El chat del CEO sobre el adaptador real de Anthropic con Sonnet 5.5 SIMULADO (M52C-A): `MockTransport`, ninguna red,
ningún gasto.

Cubre el ciclo completo `thinking → tool_use → tool_result → thinking → text`, que el razonamiento privado NO se guarda
ni se enseña, el esfuerzo que
llega al modelo, y que agotar `max_tokens` o un rechazo no se presentan como una respuesta completa."""

import json

import httpx
import pytest
from ceo_chat_test_support import OWNER, ScriptedProvider, say
from mission_test_support import recovered_mission
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo_chat.provider import AnthropicMessagesProvider
from app.ceo_chat.service import CEOChatService
from app.core.config import Settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.ceo_chat import CeoActionProposal, CeoConversation, CeoMessage

MODEL = "claude-sonnet-5-5"
PRIVATE = "RAZONAMIENTO-PRIVADO-XYZ"
SIG = "sig/AAAA+bbbb==cccc"
THINKING_1 = {"type": "thinking", "thinking": PRIVATE, "signature": SIG}
THINKING_2 = {"type": "thinking", "thinking": "", "signature": "sig/SEGUNDO+1234=="}
REDACTED = {"type": "redacted_thinking", "data": "EmwKAhgBEgy3va3pzix/LafPsn4aDFIT2Xlxh0L5L8rLVyIw=="}
TOOL_USE = {"type": "tool_use", "id": "toolu_01A", "name": "get_budget_status", "input": {}}
FINAL = {"type": "text", "text": "No hay un presupuesto autorizado en este momento."}
SETTINGS = Settings(_env_file=None)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def reply(content, stop_reason="end_turn", usage=(100, 20)):
    return {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop_reason,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


class Wire:
    def __init__(self, *answers: dict) -> None:
        self.answers = list(answers)
        self.bodies: list[dict] = []
        client = httpx.Client(transport=httpx.MockTransport(self._handle))
        self.provider = AnthropicMessagesProvider(api_key="test-key-not-real", model=MODEL, client=client)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(200, json=self.answers.pop(0))


def chat(db: Session, wire_or_provider, text="¿presupuesto?", settings: Settings = SETTINGS):
    mission = recovered_mission(db)
    provider = wire_or_provider.provider if isinstance(wire_or_provider, Wire) else wire_or_provider
    service = CEOChatService(db, provider=provider, manager=mission.manager, settings=settings)
    return service.chat(actor=OWNER, text=text, conversation_id=None)


def stored(db: Session) -> str:
    db.expire_all()
    parts = [[m.content, m.structured] for m in db.query(CeoMessage).all()]
    parts.extend(c.title for c in db.query(CeoConversation).all())
    parts.extend([a.action, a.after] for a in db.query(AuditLog).all())
    parts.extend(
        [p.target, p.parameters, p.reason, p.execution_result, p.error] for p in db.query(CeoActionProposal).all()
    )
    return json.dumps(parts, ensure_ascii=False, default=str)


# El ciclo completo: thinking → tool_use → tool_result → thinking → text


def test_the_full_sonnet55_cycle_returns_the_thinking_blocks_unchanged_on_the_second_request(db):
    wire = Wire(
        reply([THINKING_1, TOOL_USE], "tool_use", (900, 40)), reply([THINKING_2, FINAL], "end_turn", (1100, 60))
    )

    turn = chat(db, wire)

    first, second = wire.bodies
    assistant = second["messages"][-2]
    assert assistant["role"] == "assistant" and assistant["content"] == [
        THINKING_1,
        TOOL_USE,
    ]  # con su firma, en su orden
    assert second["messages"][-1]["content"][0]["type"] == "tool_result"
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "toolu_01A"
    # append-only: lo de la primera petición no cambia
    assert second["system"] == first["system"] and second["tools"] == first["tools"]
    assert second["messages"][: len(first["messages"])] == first["messages"]
    # el texto visible sale solo del bloque `text` de la última ronda
    assert turn.assistant_message.content == FINAL["text"]
    assert turn.usage["rounds"] == 2 and (turn.usage["input_tokens"], turn.usage["output_tokens"]) == (2000, 100)


def test_the_redacted_thinking_block_also_travels_back_intact(db):
    wire = Wire(reply([REDACTED, TOOL_USE], "tool_use"), reply([FINAL]))

    chat(db, wire)

    assert wire.bodies[1]["messages"][-2]["content"] == [REDACTED, TOOL_USE]


def test_the_private_reasoning_is_never_stored_shown_or_audited(db):
    wire = Wire(reply([THINKING_1, TOOL_USE], "tool_use"), reply([THINKING_2, FINAL]))

    turn = chat(db, wire)

    everything = stored(db)
    for secret in (PRIVATE, SIG, "sig/SEGUNDO", "thinking"):
        assert secret not in everything, secret
    assert PRIVATE not in json.dumps(
        [turn.assistant_message.content, turn.usage, [m.structured for m in turn.tool_messages]]
    )
    assert [m.role for m in db.query(CeoMessage).order_by(CeoMessage.seq)] == [
        "user",
        "system_internal",
        "tool",
        "assistant",
    ]


def test_the_next_message_of_the_conversation_does_not_replay_old_thinking(db):
    mission = recovered_mission(db)
    wire = Wire(reply([THINKING_1, FINAL]), reply([FINAL]))
    service = CEOChatService(db, provider=wire.provider, manager=mission.manager, settings=SETTINGS)
    first = service.chat(actor=OWNER, text="hola", conversation_id=None)

    service.chat(actor=OWNER, text="¿seguimos?", conversation_id=first.conversation.id)

    sent = json.dumps(wire.bodies[1]["messages"], ensure_ascii=False)
    assert PRIVATE not in sent and SIG not in sent
    assert wire.bodies[1]["messages"][0] == {"role": "user", "content": "hola"}


def test_the_effort_reaches_the_model_on_every_round(db):
    wire = Wire(reply([THINKING_1, TOOL_USE], "tool_use"), reply([FINAL]))

    chat(db, wire)

    assert [b["output_config"] for b in wire.bodies] == [{"effort": "medium"}, {"effort": "medium"}]
    assert all(b["max_tokens"] == 1024 for b in wire.bodies)
    assert all("thinking" not in b and "tool_choice" not in b for b in wire.bodies)


@pytest.mark.parametrize("effort", ["low", "high"])
def test_the_configured_effort_is_what_is_sent(db, effort):
    wire = Wire(reply([FINAL]))

    chat(db, wire, settings=Settings(_env_file=None, ceo_chat_effort=effort))

    assert wire.bodies[0]["output_config"] == {"effort": effort}


def test_the_scripted_provider_receives_the_configured_effort_and_keeps_working(db):
    provider = ScriptedProvider([say("ok")])

    turn = chat(db, provider)

    assert provider.requests[0].effort == "medium" and turn.assistant_message.content == "ok"


# M. el límite de salida y el rechazo no se presentan como una respuesta completa


def test_M_running_out_of_output_tokens_is_a_controlled_incomplete_state_not_a_normal_answer(db):
    partial = {"type": "text", "text": "El presupuesto es de 2,00, de los cuales"}
    wire = Wire(reply([THINKING_2, partial], "max_tokens", (1000, 1024)))

    turn = chat(db, wire)

    assert turn.usage["stopped"] == "max_output_tokens"
    content = turn.assistant_message.content
    assert content.startswith(partial["text"]) and "incompleta" in content.lower() and "límite" in content.lower()
    assert turn.proposals == []


def test_M_hitting_the_limit_with_nothing_visible_says_so(db):
    wire = Wire(reply([THINKING_2], "max_tokens", (1000, 1024)))

    turn = chat(db, wire)

    assert turn.usage["stopped"] == "max_output_tokens"
    assert (
        "incompleta" in turn.assistant_message.content.lower() and turn.assistant_message.content != "(sin respuesta)"
    )


def test_M_a_tool_call_cut_off_by_the_limit_is_never_executed(db):
    wire = Wire(reply([THINKING_1, {**TOOL_USE, "input": {}}], "max_tokens", (1000, 1024)))

    turn = chat(db, wire)

    assert turn.tool_messages == [] and turn.usage["stopped"] == "max_output_tokens"
    assert len(wire.bodies) == 1  # no hay segunda ronda con una llamada que pudo quedar truncada


def test_M_a_refusal_is_a_controlled_state(db):
    wire = Wire(reply([THINKING_2], "refusal", (500, 5)))

    turn = chat(db, wire)

    assert turn.usage["stopped"] == "refusal" and "no puedo" in turn.assistant_message.content.lower()


def test_a_normal_end_of_turn_has_no_stopped_marker(db):
    wire = Wire(reply([FINAL]))

    turn = chat(db, wire)

    assert turn.usage["stopped"] is None and turn.assistant_message.content == FINAL["text"]
