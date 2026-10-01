"""Veinte peticiones iguales a la vez producen un solo efecto (hardening pre-M44, ADR 0025).

SQLite serializa las transacciones y nunca reproduce la carrera; aquí cada hilo tiene su propia sesión, en una base
PostgreSQL efímera, y arrancan juntos tras una barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el
orden en que se intercalen, el efecto ocurre **una vez**, y cada petición recibe o el resultado original o un 409;
ninguna lo repite.
"""

import threading
import time

from pg_test_support import ephemeral_postgres
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.auth.actor import Actor, ActorSource, RoleName
from app.core.config import Settings
from app.core.errors import IdempotencyInProgressError
from app.db.models.idempotency_record import IdempotencyRecord
from app.idempotency.service import COMPLETED, run_idempotent

OWNER = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)


class Out(BaseModel):
    value: int


def run_together(engine, jobs: list) -> list:
    barrier = threading.Barrier(len(jobs))
    results: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                outcome = job(session)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada tarea es el dato
                outcome = exc
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def request(effects: list, *, key: str = "k", payload=None, scope: str = "test.op", slow: float = 0.3):
    def job(session: Session):
        def work() -> Out:
            effects.append(1)  # el efecto «en el mundo real»
            time.sleep(slow)
            return Out(value=len(effects))

        return run_idempotent(
            session,
            scope=scope,
            identity=OWNER,
            client_key=key,
            settings=SETTINGS,
            payload=payload if payload is not None else {"x": 1},
            response=Response(),
            status_code=201,
            response_model=Out,
            work=work,
        )

    return job


def test_twenty_simultaneous_identical_requests_produce_one_effect():
    with ephemeral_postgres() as engine:
        effects: list = []

        results = run_together(engine, [request(effects)] * 20)

        assert len(effects) == 1
        winners = [r for r in results if isinstance(r, Out)]
        refused = [r for r in results if isinstance(r, IdempotencyInProgressError)]
        replays = [r for r in results if isinstance(r, dict)]
        assert len(winners) == 1
        assert len(winners) + len(refused) + len(replays) == 20  # nadie recibe otra cosa
        assert all(r == {"value": 1} for r in replays)
        with Session(engine) as db:
            [record] = db.query(IdempotencyRecord).all()
            assert record.status == COMPLETED


def test_a_retry_after_the_winner_finished_gets_the_stored_response():
    with ephemeral_postgres() as engine:
        effects: list = []
        run_together(engine, [request(effects, slow=0.0)])

        later = run_together(engine, [request(effects, slow=0.0)] * 5)

        assert len(effects) == 1
        assert later == [{"value": 1}] * 5


def test_different_keys_do_not_wait_for_each_other():
    with ephemeral_postgres() as engine:
        effects: list = []

        results = run_together(engine, [request(effects, key=f"k-{i}", slow=0.05) for i in range(10)])

        assert len(effects) == 10
        assert all(isinstance(r, Out) for r in results)


def test_simultaneous_requests_with_the_same_key_and_different_contents_cannot_both_run():
    with ephemeral_postgres() as engine:
        effects: list = []

        results = run_together(
            engine,
            [request(effects, payload={"x": 1}), request(effects, payload={"x": 2})] * 6,
        )

        assert len(effects) == 1  # solo la primera que reclamó la clave se ejecuta, sea cual sea
        assert sum(isinstance(r, Out) for r in results) == 1
