"""Apoyo compartido de las pruebas de caos y de invariantes (hardening pre-M44, fases 8 y 9).

Módulo auxiliar de tests, **no** un test. Reúne lo que se repite: lanzar N tareas a la vez tras una barrera (cada
una con su sesión), un proveedor falso lento (para que otros ejecutores **vean** la operación en curso en vez de
llegar cuando ya terminó), y las consultas de estado que usan todos los escenarios.

Cuando hay una carrera se sincroniza con barreras explícitas, no con esperas «suficientes».
"""

import datetime
import threading
import time

from action_test_support import FakeProviderAdapter
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models.budget import BudgetAllocation
from app.db.models.external_action import ExternalAction
from app.db.models.job import Job
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.gates.action_gate import SideEffectAction
from app.jobs.worker import Worker
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

OWNER = "owner@amazona.local"
ADS = SideEffectAction.ACTIVATE_ADS.value


def request(amount: float = 60_000.0, sale_price: float = 50.0) -> PipelineRequest:
    """Una ejecución del pipeline cuyo paso de marketing gasta `amount`. Con `sale_price` alto el análisis económico
    sale GO y los pasos con efecto no piden aprobación; con `0.5` sale NO_GO y cada uno pregunta."""
    return PipelineRequest(
        category="home", sale_price=sale_price, destination_region="mexico", market="us", daily_budget=amount
    )


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def use_provider(monkeypatch, *behaviors: str, **kwargs) -> FakeProviderAdapter:
    """Sustituye el adaptador por defecto (el worker construye su propio orquestador). Las conductas solo se aplican a
    la acción de marketing; los demás pasos con efecto van siempre bien."""
    fake = FakeProviderAdapter(behaviors=list(behaviors), only_operation=ADS, **kwargs)
    monkeypatch.setattr("app.pipeline.service.SimulatedAdapter", lambda: fake)
    return fake


class SlowProvider(FakeProviderAdapter):
    """Un proveedor lento: mientras responde, los demás ejecutores miran la operación y la ven en curso."""

    def __init__(self, *args, delay: float = 0.4, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._delay = delay

    def execute(self, request):
        time.sleep(self._delay)
        return super().execute(request)


def ads_actions(db: Session) -> list[ExternalAction]:
    db.expire_all()
    return (
        db.query(ExternalAction)
        .filter_by(operation=ADS)
        .order_by(ExternalAction.created_at, ExternalAction.sequence)
        .all()
    )


def ledger(db: Session) -> tuple[float, float]:
    """`(reservado, comprometido)`."""
    db.expire_all()
    row = db.query(BudgetAllocation).one()
    return float(row.reserved), float(row.committed)


def marketing_step(db: Session, run: PipelineRun) -> PipelineStep:
    db.expire_all()
    return db.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="marketing").one()


def expire_lease(db: Session, run: PipelineRun) -> None:
    job = db.get(Job, run.job_id)
    job.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    db.commit()


def resume(db: Session, run: PipelineRun) -> None:
    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run.id), actor=OWNER)
    drain(db)


def run_together(engine, jobs: list) -> list:
    """Lanza todas las tareas a la vez, cada una con su sesión, tras una barrera; devuelve lo que devolvió (o lanzó)
    cada una."""
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


def scalar(engine, sql: str):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def errors(results: list) -> list[Exception]:
    return [r for r in results if isinstance(r, Exception)]
