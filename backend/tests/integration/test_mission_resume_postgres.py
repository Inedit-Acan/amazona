"""Reanudaciones concurrentes de la misma misión: solo una puede ejecutar (M50, Commit 9, casos J y K).

Una carrera entre transacciones solo existe en un PostgreSQL de verdad. La garantía es doble y mínima: la reanudación
bloquea la fila del PROYECTO (`SELECT … FOR UPDATE`) durante toda la operación y exige la decisión que el cliente vio
(`after_decision_id`). Quien llega después espera, ve la decisión nueva y se rechaza con un conflicto: nunca dos
ejecuciones de la misma tarea, ni dos decisiones para la misma petición.

Solo contra un PostgreSQL local o efímero (`pg_test_support`): si no hay, se omiten."""

import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

from mission_test_support import FlakyFinance, counts, recovered_mission
from pg_test_support import ephemeral_postgres
from sqlalchemy.orm import sessionmaker

from app.agents.finance import FinanceAgent
from app.ceo.orchestrator import CEOOrchestrator
from app.core.errors import ConflictError
from app.db.models.agent_execution_log import AgentExecutionLog
from app.db.models.decision import Decision


class SlowFinance(FinanceAgent):
    """Tarda: mantiene el bloqueo el tiempo suficiente para que los demás hilos lleguen y esperen."""

    def __init__(self, delay: float = 0.8) -> None:
        super().__init__()
        self.delay = delay
        self.calls = 0
        self.lock = threading.Lock()

    def run(self, task_input: dict):
        time.sleep(self.delay)
        with self.lock:
            self.calls += 1
        return super().run(task_input)


def race(factory, manager, project_id: str, decision_id: str, workers: int) -> list[str]:
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    guard = threading.Lock()

    def worker() -> None:
        session = factory()
        try:
            barrier.wait(timeout=10)
            CEOOrchestrator(session, agent_manager=manager, max_task_retries=0).resume_project(
                project_id, actor="ceo", after_decision_id=decision_id
            )
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
        thread.join(timeout=90)
    return outcomes


def prepare(factory):
    finance = SlowFinance()
    with factory() as db:
        mission = recovered_mission(db, overrides={"agent-finance-1": finance})
        return finance, mission.manager, mission.project.id, mission.latest().id


def state(factory, project_id: str) -> tuple[int, int, int]:
    with factory() as db:
        decisions = db.query(Decision).filter_by(project_id=project_id).count()
        finance_runs = db.query(AgentExecutionLog).filter_by(agent_id="agent-finance-1").count()
        return decisions, finance_runs, counts(db)["tasks"]


def test_J_two_concurrent_resumes_only_one_executes():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        finance, manager, project_id, decision_id = prepare(factory)

        outcomes = race(factory, manager, project_id, decision_id, workers=2)

        assert sorted(outcomes) == ["conflict", "won"], outcomes
        assert state(factory, project_id) == (2, 1, 5)  # la decisión vieja y UNA nueva; finanzas se ejecutó una vez
        assert finance.calls == 1


def test_K_five_concurrent_resumes_leave_exactly_one_new_decision_and_no_duplicate_work():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        finance, manager, project_id, decision_id = prepare(factory)

        outcomes = race(factory, manager, project_id, decision_id, workers=5)

        assert outcomes.count("won") == 1, outcomes
        assert outcomes.count("conflict") == 4, outcomes
        assert state(factory, project_id) == (2, 1, 5)
        assert finance.calls == 1
        with factory() as db:
            keys = [(r.task_id, r.attempt) for r in db.query(AgentExecutionLog).all()]
            assert len(keys) == len(set(keys))  # nunca dos filas con el mismo (tarea, intento)


@contextmanager
def slow_conclusion(delay: float = 0.6):
    """Alarga la sección crítica final (la decisión), para que, SIN el bloqueo del proyecto, los hilos estén dentro a
    la vez."""
    original = CEOOrchestrator._conclude

    def slow(self, *args, **kwargs):
        time.sleep(delay)
        return original(self, *args, **kwargs)

    with patch.object(CEOOrchestrator, "_conclude", slow):
        yield


def prepare_synthesis_only(factory):
    """Solo queda la síntesis: ningún agente por medio. Es el caso en que NADA más serializa a las reanudaciones (no hay
    filas de tareas que actualizar antes de decidir): lo único que impide dos decisiones es el bloqueo del proyecto."""
    finance = FlakyFinance(failures=1)
    with factory() as db:
        mission = recovered_mission(db, overrides={"agent-finance-1": finance})
        mission.resume()  # finanzas falla: decisión incompleta
        mission.retry("finance_validation", after_attempt=1)  # Commit 8: se recupera y la síntesis queda PENDING
        assert mission.task("decision_synthesis").status == "PENDING"
        return mission.manager, mission.project.id, mission.latest().id


def decisions_of(factory, project_id: str) -> int:
    with factory() as db:
        return db.query(Decision).filter_by(project_id=project_id).count()


def test_J2_two_concurrent_resumes_of_the_synthesis_alone_write_one_decision():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        manager, project_id, decision_id = prepare_synthesis_only(factory)
        assert decisions_of(factory, project_id) == 2

        with slow_conclusion():
            outcomes = race(factory, manager, project_id, decision_id, workers=2)

        assert sorted(outcomes) == ["conflict", "won"], outcomes
        assert decisions_of(factory, project_id) == 3  # la incompleta, la de la reanudación fallida y UNA nueva


def test_K2_five_concurrent_resumes_of_the_synthesis_alone_write_one_decision():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        manager, project_id, decision_id = prepare_synthesis_only(factory)

        with slow_conclusion():
            outcomes = race(factory, manager, project_id, decision_id, workers=5)

        assert outcomes.count("won") == 1 and outcomes.count("conflict") == 4, outcomes
        assert decisions_of(factory, project_id) == 3


def test_a_resume_after_the_race_names_the_new_decision_and_is_refused_because_the_mission_is_complete():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        _, manager, project_id, decision_id = prepare(factory)
        race(factory, manager, project_id, decision_id, workers=2)

        with factory() as db:
            latest = db.query(Decision).filter_by(project_id=project_id).order_by(Decision.created_at).all()[-1].id
            try:
                CEOOrchestrator(db, agent_manager=manager).resume_project(
                    project_id, actor="ceo", after_decision_id=latest
                )
            except ConflictError as exc:
                assert "complete" in str(exc)
            else:  # pragma: no cover - el fallo es lo que se prueba
                raise AssertionError("a complete mission was resumed")
