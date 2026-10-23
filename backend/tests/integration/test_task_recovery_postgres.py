"""Dos reintentos concurrentes de la misma tarea: solo uno puede ganar (M49, Commit 8, caso T).

Una carrera entre transacciones solo existe en un PostgreSQL de verdad (SQLite serializa todo). La protección es
MÍNIMA y suficiente: el reintento bloquea la fila de la tarea (`SELECT … FOR UPDATE`) durante toda la operación y
exige el intento que repite (`after_attempt`). Quien llega segundo espera a que el primero confirme y entonces ve
OTRO estado (COMPLETED, o el intento siguiente): se rechaza con un conflicto. Nunca hay dos ejecuciones del mismo
intento ni dos filas con el mismo `attempt`.

Solo contra un PostgreSQL local o efímero (`pg_test_support`): si no hay, se omiten.
"""

import threading
import time

from pg_test_support import ephemeral_postgres
from recovery_test_support import Scripted, build_manager, executions_of, run_mission, tasks_by_name
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentResult
from app.core.errors import ConflictError
from app.db.models.task import Task
from app.tasks.recovery import TaskRecoveryService

P1 = "agent-product-1"


class Slow(Scripted):
    """Como `Scripted`, pero tarda: mantiene el bloqueo el tiempo suficiente para que el otro hilo llegue y espere."""

    def __init__(self, script, delay: float = 0.6) -> None:
        super().__init__(script)
        self.delay = delay
        self.lock = threading.Lock()

    def run(self, task_input: dict) -> AgentResult:
        time.sleep(self.delay)
        with self.lock:
            return super().run(task_input)


def race(factory, manager, task_id: str, workers: int, after_attempt: int):
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    guard = threading.Lock()

    def worker() -> None:
        session = factory()
        try:
            barrier.wait(timeout=10)
            TaskRecoveryService(session, manager).retry(
                task_id, actor="ceo", after_attempt=after_attempt, reason="race"
            )
            session.commit()
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
    return outcomes


def prepare(factory, script):
    agent = Slow(script)
    _, manager = build_manager({P1: agent})
    with factory() as db:
        run_mission(db, manager, max_task_retries=0)  # el intento 1 falla: la tarea queda FAILED
        task = tasks_by_name(db)["product_validation"]
        assert task.status == "FAILED"
        return agent, manager, task.id


def attempts(factory, task_id: str) -> list[tuple[int, bool]]:
    with factory() as db:
        task = db.get(Task, task_id)
        return [(r.attempt, r.success) for r in executions_of(db, task)]


def test_T_two_concurrent_retries_of_the_same_attempt_only_one_wins_when_it_completes():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        agent, manager, task_id = prepare(factory, [False, True])

        outcomes = race(factory, manager, task_id, workers=2, after_attempt=1)

        assert sorted(outcomes) == ["conflict", "won"], outcomes
        assert attempts(factory, task_id) == [(1, False), (2, True)]
        assert agent.calls == 2  # el intento 1 y UNA sola ejecución del retry
        with factory() as db:
            assert db.get(Task, task_id).status == "COMPLETED"


def test_T2_the_loser_also_loses_when_the_winner_fails_again_because_it_names_a_stale_attempt():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        agent, manager, task_id = prepare(factory, [False, False, True])

        outcomes = race(factory, manager, task_id, workers=2, after_attempt=1)

        assert sorted(outcomes) == ["conflict", "won"], outcomes
        assert attempts(factory, task_id) == [(1, False), (2, False)]  # nunca dos intentos «2»
        with factory() as db:
            assert db.get(Task, task_id).status == "FAILED"


def test_T3_five_concurrent_retries_leave_exactly_one_new_attempt_and_unique_numbers():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        agent, manager, task_id = prepare(factory, [False, False, False, False])

        outcomes = race(factory, manager, task_id, workers=5, after_attempt=1)

        assert outcomes.count("won") == 1, outcomes
        assert outcomes.count("conflict") == 4, outcomes
        numbers = [number for number, _ in attempts(factory, task_id)]
        assert numbers == [1, 2]
        assert len(numbers) == len(set(numbers))


def test_T4_a_retry_after_the_race_names_the_new_attempt_and_goes_on_numbering():
    with ephemeral_postgres() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        agent, manager, task_id = prepare(factory, [False, False, True])
        race(factory, manager, task_id, workers=2, after_attempt=1)

        with factory() as db:
            TaskRecoveryService(db, manager).retry(task_id, actor="ceo", after_attempt=2, reason=None)
            db.commit()

        assert attempts(factory, task_id) == [(1, False), (2, False), (3, True)]
