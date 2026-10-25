"""El chat con el CEO contra un PostgreSQL de verdad (M52): lo que SQLite no puede reproducir.

- Confirmar a la vez: de N confirmaciones de la misma propuesta, UNA gana (compare-and-set `PROPOSED → EXECUTING`) y la
  tarea se reintenta una sola vez.
- Dos mensajes a la vez en la misma conversación: se numeran uno detrás de otro, sin chocar con la clave única
  `(conversation_id, seq)`.
- El esquema de los modelos admite lo que la migración admite (tablas, restricciones) y rechaza lo que debe.

Solo contra un PostgreSQL local o efímero (`pg_test_support`): si no hay, se omiten."""

import threading
import time

import pytest
from ceo_chat_test_support import OWNER, ScriptedProvider, call, say
from mission_test_support import P1
from pg_test_support import ephemeral_postgres
from recovery_test_support import Scripted, build_manager, make_objective
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentResult
from app.ceo.orchestrator import CEOOrchestrator
from app.ceo_chat import store
from app.ceo_chat.actions import ActionService
from app.ceo_chat.service import CEOChatService
from app.core.config import Settings
from app.core.errors import ConflictError
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.ceo_chat import CeoActionProposal, CeoConversation, CeoMessage
from app.db.models.task import Task

SETTINGS = Settings(_env_file=None)


class Slow(Scripted):
    """Tarda: mantiene la operación el tiempo suficiente para que los otros hilos lleguen y esperen."""

    def __init__(self, script, delay: float = 0.5) -> None:
        super().__init__(script)
        self.delay = delay
        self.lock = threading.Lock()

    def run(self, task_input: dict) -> AgentResult:
        time.sleep(self.delay)
        with self.lock:
            return super().run(task_input)


def test_confirming_the_same_proposal_at_once_executes_it_exactly_once():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        agent = Slow([False, True])
        _, manager = build_manager({P1: agent})
        with factory() as db:
            CEOOrchestrator(db, agent_manager=manager, max_task_retries=0).run_objective(make_objective(db).id)
            task_id = db.query(Task).filter_by(name="product_validation").one().id
            chat = CEOChatService(
                db,
                provider=ScriptedProvider(
                    [
                        call(("propose_retry_task", {"task_id": task_id, "after_attempt": 1, "reason": "reintento"})),
                        say("Propuesta."),
                    ]
                ),
                manager=manager,
                settings=SETTINGS,
            )
            proposal_id = chat.chat(actor=OWNER, text="propón", conversation_id=None).proposals[0].id

        workers = 4
        barrier = threading.Barrier(workers)
        outcomes: list[str] = []
        guard = threading.Lock()

        def worker() -> None:
            session = factory()
            try:
                barrier.wait(timeout=10)
                ActionService(session, manager, SETTINGS).confirm(OWNER, proposal_id)
                result = "won"
            except ConflictError:
                session.rollback()
                result = "conflict"
            except Exception as exc:  # noqa: BLE001 - cualquier otra cosa es un fallo del producto, y se ve
                session.rollback()
                result = f"error:{type(exc).__name__}:{exc}"
            finally:
                session.close()
            with guard:
                outcomes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert sorted(outcomes) == ["conflict"] * (workers - 1) + ["won"], outcomes
        with factory() as db:
            assert [
                (r.attempt, r.success)
                for r in db.query(AgentExecutionLog).filter_by(task_id=task_id).order_by(AgentExecutionLog.attempt)
            ] == [
                (1, False),
                (2, True),
            ]
            assert db.get(CeoActionProposal, proposal_id).status == "EXECUTED"
            assert db.get(Task, task_id).status == "COMPLETED"
        assert agent.calls == 2  # el intento original y UN reintento


def test_two_messages_at_once_in_the_same_conversation_are_numbered_one_after_the_other():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            conversation = CeoConversation(owner_subject=OWNER.subject)
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id
        per_worker, workers = 8, 3
        barrier = threading.Barrier(workers)
        errors: list[str] = []

        def worker(name: str) -> None:
            session = factory()
            try:
                barrier.wait(timeout=10)
                for index in range(per_worker):
                    store.add_message(session, conversation_id, "user", f"{name}-{index}")
                    session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                errors.append(f"{type(exc).__name__}: {exc}")
            finally:
                session.close()

        threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert errors == []
        with factory() as db:
            seqs = [
                m.seq
                for m in db.scalars(
                    select(CeoMessage).where(CeoMessage.conversation_id == conversation_id).order_by(CeoMessage.seq)
                )
            ]
        assert seqs == list(range(1, per_worker * workers + 1))


def test_the_schema_rejects_what_the_chat_must_never_store():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            conversation = CeoConversation(owner_subject="s")
            db.add(conversation)
            db.commit()
            for role in ("system", "admin"):
                with pytest.raises(IntegrityError):
                    db.add(CeoMessage(conversation_id=conversation.id, seq=1, role=role, content="x"))
                    db.commit()
                db.rollback()
            db.add(CeoMessage(conversation_id=conversation.id, seq=1, role="system_internal", content=""))
            db.commit()
            with pytest.raises(IntegrityError):  # la misma posición dos veces
                db.add(CeoMessage(conversation_id=conversation.id, seq=1, role="user", content="x"))
                db.commit()
            db.rollback()
            for bad in ({"action_type": "run_sql"}, {"status": "DONE"}, {"risk_level": "extreme"}):
                with pytest.raises(IntegrityError):
                    db.add(
                        CeoActionProposal(
                            conversation_id=conversation.id,
                            **{
                                "action_type": "retry_task",
                                "target": {},
                                "parameters": {},
                                "estimated_effects": {},
                                "risk_level": "low",
                                "status": "PROPOSED",
                                **bad,
                            },
                        )
                    )
                    db.commit()
                db.rollback()
            assert db.execute(text("select count(*) from ceo_action_proposals")).scalar() == 0
