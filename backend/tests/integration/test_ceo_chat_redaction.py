"""Lo que se PERSISTE de una conversación con el CEO también va redactado (M52, cierre).

El texto del propietario y la respuesta del asistente pueden llevar un secreto por accidente (alguien pega un token, el
modelo repite una clave). El
redactor es EL de siempre (`app.ceo_chat.redaction`), aplicado en el único sitio por el que pasa todo mensaje
(`store.add_message`): ni el modelo, ni la base,
ni la respuesta al frontend conservan el valor crudo. Lo normal se conserva idéntico."""

import json

import pytest
from ceo_chat_test_support import OWNER, ScriptedProvider, call, say
from mission_test_support import incomplete_mission, recovered_mission
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ceo_chat import store
from app.ceo_chat.actions import ActionService
from app.ceo_chat.service import CEOChatService
from app.core.config import Settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.ceo_chat import CeoActionProposal, CeoConversation, CeoMessage

SETTINGS = Settings(_env_file=None)

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"
BEARER_VALUE = "abcDEF1234567890xyz"
SK = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA"
DSN_PASSWORD = "SuperSecreta"

#: (nombre, lo que se pega, el fragmento CRUDO que no puede quedar en ningún sitio)
SECRETS = [
    ("jwt", f"mi token es {JWT} gracias", JWT),
    ("bearer", f"cabecera Authorization: Bearer {BEARER_VALUE} fin", BEARER_VALUE),
    ("sk", f"mi API key es {SK} ok", SK),
    ("password", "la contraseña: password=hunter2 ya", "hunter2"),
    ("dsn", f"conecta con postgresql+psycopg://u:{DSN_PASSWORD}@host/db por favor", DSN_PASSWORD),
]


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


def chat_with(db: Session, mission, *steps) -> tuple[CEOChatService, ScriptedProvider]:
    provider = ScriptedProvider(list(steps))
    return CEOChatService(db, provider=provider, manager=mission.manager, settings=SETTINGS), provider


def everything_stored(db: Session) -> str:
    """TODO lo que el chat deja en la base, como un solo texto: mensajes, estructurados, títulos, auditoría y
    propuestas."""
    db.expire_all()
    parts: list = []
    for m in db.query(CeoMessage).all():
        parts.append([m.content, m.structured, m.provider, m.model])
    parts.extend(c.title for c in db.query(CeoConversation).all())
    parts.extend([a.action, a.resource, a.after] for a in db.query(AuditLog).all() if a.action.startswith("ceo."))
    for p in db.query(CeoActionProposal).all():
        parts.append([p.target, p.parameters, p.reason, p.estimated_effects, p.execution_result, p.error])
    return json.dumps(parts, ensure_ascii=False, default=str)


# A / B. lo normal no se toca


@pytest.mark.parametrize(
    "text",
    [
        "¿Cuál es el presupuesto actual?",
        "Reintenta la tarea 3f2a9c1e-7b44-4d0e-9a51-0c1d2e3f4a5b tras el intento: 1, por favor.",
        "Analiza el estado: 2 misiones, 5 tareas (3 completadas) y el coste de 0,00 €. ¿Cuántos tokens se usaron?",
        "Decisión V2 = GO; confianza=0.9 y puntuación: 0.8",
    ],
)
def test_A_a_normal_user_message_is_stored_exactly_as_written(db, text):
    mission = recovered_mission(db)
    chat, provider = chat_with(db, mission, say("ok"))

    turn = chat.chat(actor=OWNER, text=text, conversation_id=None)

    assert turn.user_message.content == text
    assert db.query(CeoMessage).filter_by(role="user").one().content == text
    assert provider.requests[0].messages[-1].content == text


@pytest.mark.parametrize(
    "answer",
    [
        "La última misión está completa (decisión V2: GO). Fuente: Última misión.\n"
        "- Hecho: 5 tareas.\n- Inferencia: todo bien.",
        "Presupuesto: 2,00 € autorizados; reservado 0,00; confianza=0.9.",
    ],
)
def test_B_a_normal_assistant_message_is_stored_exactly_as_answered(db, answer):
    mission = recovered_mission(db)
    chat, _ = chat_with(db, mission, say(answer))

    turn = chat.chat(actor=OWNER, text="estado", conversation_id=None)

    assert turn.assistant_message.content == answer
    assert db.query(CeoMessage).filter_by(role="assistant").one().content == answer


# C / D / E / F. el usuario pega un secreto


@pytest.mark.parametrize(("name", "text", "raw"), SECRETS, ids=[s[0] for s in SECRETS])
def test_C_D_E_F_a_secret_pasted_by_the_user_is_never_stored_sent_or_returned(db, name, text, raw):
    mission = recovered_mission(db)
    chat, provider = chat_with(db, mission, say("Recibido."))

    turn = chat.chat(actor=OWNER, text=text, conversation_id=None)

    assert raw not in everything_stored(db)  # ni mensajes, ni estructurados, ni título, ni auditoría
    assert raw not in turn.user_message.content  # lo que se devuelve al frontend
    sent = json.dumps(
        [[r.system, [(m.role, m.content) for m in r.messages]] for r in provider.requests], ensure_ascii=False
    )
    assert raw not in sent  # lo que ve el modelo
    assert "[" in turn.user_message.content  # quedó una marca de redacción, no un hueco
    assert turn.user_message.content.startswith(text[:6])  # el resto del mensaje sigue ahí


def test_a_secret_in_the_first_message_does_not_reach_the_model_in_later_turns_either(db):
    mission = recovered_mission(db)
    chat, provider = chat_with(db, mission, say("Hola."), say("Seguimos."))
    first = chat.chat(actor=OWNER, text=f"mi API key es {SK}", conversation_id=None)

    chat.chat(actor=OWNER, text="¿seguimos?", conversation_id=first.conversation.id)

    assert SK not in json.dumps([[(m.role, m.content) for m in r.messages] for r in provider.requests])


# G. el modelo devuelve un secreto


def test_G_a_secret_in_the_assistant_answer_is_not_stored_nor_returned(db):
    mission = recovered_mission(db)
    chat, _ = chat_with(db, mission, say(f"Tu clave es {SK} y la contraseña: password=hunter2. Bearer {BEARER_VALUE}"))

    turn = chat.chat(actor=OWNER, text="dame las claves", conversation_id=None)

    for raw in (SK, "hunter2", BEARER_VALUE):
        assert raw not in turn.assistant_message.content
        assert raw not in everything_stored(db)
    assert turn.assistant_message.content.startswith("Tu clave es ")


# H. estructurados


def test_H_structured_payloads_are_redacted_at_the_single_door_for_every_message(db):
    mission = recovered_mission(db)
    conversation = CeoConversation(owner_subject=OWNER.subject)
    db.add(conversation)
    db.flush()

    for role in ("tool", "system_internal", "assistant"):
        store.add_message(
            db,
            conversation.id,
            role,
            f"nota con {SK}",
            {
                "result": {"api_key": "valor-crudo", "note": f"Bearer {BEARER_VALUE}", "ok": 1},
                "list": [f"password=hunter2 {JWT}"],
            },
        )
    db.commit()

    stored = everything_stored(db)
    for raw in (SK, "valor-crudo", BEARER_VALUE, "hunter2", JWT):
        assert raw not in stored, raw
    row = db.query(CeoMessage).filter_by(role="tool").one()
    assert row.structured["result"]["ok"] == 1  # lo que no es secreto se conserva
    assert mission is not None


def test_H_a_tool_call_that_carries_a_secret_is_stored_redacted(db):
    mission = incomplete_mission(db)
    task_id = mission.task("product_validation").id
    chat, _ = chat_with(
        db,
        mission,
        call(
            (
                "propose_retry_task",
                {"task_id": task_id, "after_attempt": 1, "reason": f"reintento; password=hunter2 {SK}"},
            )
        ),
        say("Propuesta lista."),
    )

    chat.chat(actor=OWNER, text="propón un reintento", conversation_id=None)

    stored = everything_stored(db)
    assert "hunter2" not in stored and SK not in stored
    assert db.query(CeoActionProposal).one().status == "PROPOSED"  # K: la propuesta se creó igualmente


# I. auditoría


def test_I_the_audit_still_carries_no_message_text_or_secrets(db):
    mission = recovered_mission(db)
    chat, _ = chat_with(db, mission, say(f"clave {SK}"))

    chat.chat(actor=OWNER, text=f"mi password=hunter2 y {JWT}", conversation_id=None)

    audit = json.dumps([a.after for a in db.query(AuditLog).all() if a.action.startswith("ceo.")], default=str)
    assert "hunter2" not in audit and JWT not in audit and SK not in audit and "mi password" not in audit


# K. no rompe el tool calling, las propuestas ni la confirmación


def test_K_redaction_does_not_break_tool_calling_proposals_or_confirmation(db):
    mission = incomplete_mission(db)
    task_id = mission.task("product_validation").id
    chat, provider = chat_with(
        db,
        mission,
        call(
            ("get_budget_status", {}),
            ("propose_retry_task", {"task_id": task_id, "after_attempt": 1, "reason": "fallo transitorio"}),
        ),
        say("Te propongo reintentar product_validation."),
    )

    turn = chat.chat(actor=OWNER, text=f"reintenta product_validation; mi key es {SK}", conversation_id=None)

    assert [m.structured["tool"] for m in turn.tool_messages] == ["get_budget_status", "propose_retry_task"]
    assert all(m.structured["error"] is None for m in turn.tool_messages)
    assert [p.status for p in turn.proposals] == ["PROPOSED"] and turn.proposals[0].parameters["task_id"] == task_id
    assert turn.assistant_message.content == "Te propongo reintentar product_validation."
    assert len(provider.requests) == 2
    ActionService(db, mission.manager, SETTINGS).confirm(OWNER, turn.proposals[0].id)  # y confirmar sigue ejecutando
    assert mission.task("product_validation").status == "COMPLETED"
    assert SK not in everything_stored(db)
