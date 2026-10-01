"""Dos ejecutores sobre la misma acción externa no pueden ganar los dos (hardening pre-M44, ADR 0024).

SQLite serializa todas las transacciones y nunca reproduce estas carreras; aquí cada hilo tiene su propia
sesión, en una base PostgreSQL efímera, y arrancan a la vez tras una barrera. Lo que se afirma son invariantes,
no tiempos: sea cual sea el orden en que se intercalen,

- una operación (`reference`) tiene a lo sumo una abierta, y todos los que la piden reciben la misma;
- el proveedor recibe **a lo sumo una** petición por operación (el efecto no se duplica);
- una reserva no se libera si la petición llegó a salir;
- una operación de resultado desconocido se cierra una sola vez y el libro se mueve una sola vez.
"""

import datetime
import threading
import time

from action_test_support import FakeProviderAdapter
from pg_test_support import ephemeral_postgres
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService, ExternalActionStateError
from app.budgets.service import BudgetLedgerService
from app.core.errors import ExternalOutcomeUnknownError
from app.db.models.external_action import ExternalAction

OWNER = "owner@amazona.local"
REFERENCE = "pipeline_step:run-1:marketing"
PAYLOAD = {"platform": "meta", "daily_budget": 100.0}


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


def authorise(engine) -> None:
    with Session(engine) as db:
        BudgetLedgerService(db).authorise_budget(hard_limit=1_000.0, actor=OWNER)


def ledger(engine) -> tuple[float, float]:
    with engine.connect() as connection:
        row = connection.execute(text("SELECT reserved, committed FROM budget_allocations")).one()
        return float(row[0]), float(row[1])


def prepare(engine, adapter, reference: str = REFERENCE, amount: float = 100.0) -> str:
    with Session(engine) as db:
        service = ExternalActionService(db)
        action = service.open(
            reference=reference,
            adapter=adapter,
            operation="activate_ads",
            amount=amount,
            payload=PAYLOAD,
            correlation_id="corr-1",
        )
        assert service.reserve(action)
        db.commit()
        return action.id


def status_of(engine, action_id: str) -> str:
    with Session(engine) as db:
        return db.get(ExternalAction, action_id).status


def errors(results: list) -> list[Exception]:
    return [r for r in results if isinstance(r, Exception)]


def test_twelve_simultaneous_requests_to_open_the_same_operation_get_one_operation():
    with ephemeral_postgres() as engine:
        adapter = FakeProviderAdapter()

        def open_job(session: Session) -> str:
            service = ExternalActionService(session)
            action = service.open(
                reference=REFERENCE,
                adapter=adapter,
                operation="activate_ads",
                amount=100.0,
                payload=PAYLOAD,
                correlation_id="corr-1",
            )
            session.commit()
            return action.id

        results = run_together(engine, [open_job] * 12)

        assert errors(results) == []
        assert len(set(results)) == 1  # todos reciben la misma operación
        with Session(engine) as db:
            assert db.query(ExternalAction).count() == 1


def test_two_executors_of_the_same_operation_send_exactly_one_request():
    with ephemeral_postgres() as engine:
        authorise(engine)
        adapter = FakeProviderAdapter()
        action_id = prepare(engine, adapter)

        def execute_job(session: Session):
            service = ExternalActionService(session)
            service.execute(session.get(ExternalAction, action_id), adapter, PAYLOAD)
            return "done"

        results = run_together(engine, [execute_job] * 6)

        assert len(adapter.requests) == 1  # una sola petición salió hacia el proveedor
        assert adapter.effect_count == 1
        # Quien llega cuando ya está hecha recibe «ya hecho» (sin efecto); quien llega mientras otro la tiene entre
        # manos es rechazado. Ninguno hace una segunda llamada.
        assert results.count("done") >= 1
        assert all(isinstance(r, ExternalActionStateError) for r in errors(results))
        assert status_of(engine, action_id) == ActionStatus.SUCCEEDED.value
        assert ledger(engine) == (0.0, 100.0)  # comprometido una sola vez


class SlowProvider(FakeProviderAdapter):
    """Un proveedor lento: mientras responde, los demás ejecutores miran la operación y la ven en curso."""

    def execute(self, request):
        time.sleep(0.4)
        return super().execute(request)


def test_while_a_call_is_in_flight_every_other_executor_is_refused():
    with ephemeral_postgres() as engine:
        authorise(engine)
        adapter = SlowProvider()
        action_id = prepare(engine, adapter)

        def execute_job(session: Session):
            ExternalActionService(session).execute(session.get(ExternalAction, action_id), adapter, PAYLOAD)
            return "done"

        results = run_together(engine, [execute_job] * 6)

        assert results.count("done") == 1
        assert len(errors(results)) == 5
        assert all(isinstance(r, ExternalActionStateError) for r in errors(results))
        assert len(adapter.requests) == 1
        assert ledger(engine) == (0.0, 100.0)


def test_the_sweeper_and_the_executor_cannot_both_win_over_a_pending_operation():
    """Barrido (libera lo que nunca salió) contra ejecutor (empieza la llamada). Gane quien gane, nunca
    ocurren las dos cosas: o se libera y el proveedor no recibe nada, o se llama y no se libera."""
    for _ in range(8):
        with ephemeral_postgres() as engine:
            authorise(engine)
            adapter = FakeProviderAdapter()
            action_id = prepare(engine, adapter)

            def sweep_job(session: Session):
                return ExternalActionService(session).reconcile_interrupted(older_than=datetime.timedelta(seconds=-1))

            def execute_job(session: Session):
                service = ExternalActionService(session)
                service.execute(session.get(ExternalAction, action_id), adapter, PAYLOAD)
                return "done"

            results = run_together(engine, [sweep_job, execute_job])

            final = status_of(engine, action_id)
            if final == ActionStatus.FAILED_CONFIRMED.value:
                assert adapter.requests == []
                assert ledger(engine) == (0.0, 0.0)
            else:
                assert final == ActionStatus.SUCCEEDED.value
                assert len(adapter.requests) == 1
                assert ledger(engine) == (0.0, 100.0)
            assert [e for e in errors(results) if not isinstance(e, ExternalActionStateError)] == []


def test_two_people_resolving_the_same_unknown_outcome_move_the_ledger_once():
    with ephemeral_postgres() as engine:
        authorise(engine)
        adapter = FakeProviderAdapter(supports_idempotency=False, behaviors=["timeout_after"])
        action_id = prepare(engine, adapter)
        with Session(engine) as db:
            service = ExternalActionService(db)
            try:
                service.execute(db.get(ExternalAction, action_id), adapter, PAYLOAD)
            except ExternalOutcomeUnknownError:
                pass
        assert ledger(engine) == (100.0, 0.0)

        def resolve_job(succeeded: bool):
            def job(session: Session):
                ExternalActionService(session).resolve(
                    session.get(ExternalAction, action_id), succeeded=succeeded, actor=OWNER, reason="checked by hand"
                )
                return "resolved"

            return job

        results = run_together(engine, [resolve_job(True), resolve_job(False), resolve_job(True), resolve_job(False)])

        assert results.count("resolved") == 1
        assert all(isinstance(r, ExternalActionStateError) for r in errors(results))
        reserved, committed = ledger(engine)
        assert reserved == 0.0
        assert committed in (0.0, 100.0)  # según quién ganó, pero nunca ambas cosas
        assert status_of(engine, action_id) in (ActionStatus.SUCCEEDED.value, ActionStatus.FAILED_CONFIRMED.value)
        with engine.connect() as connection:
            moves = connection.execute(
                text("SELECT count(*) FROM financial_events WHERE type IN ('COMMIT', 'RELEASE')")
            ).scalar_one()
        assert moves == 1


def test_the_database_itself_refuses_a_second_open_operation_for_a_site():
    """Aunque alguien se saltara el servicio y su lock, el índice único parcial lo impide."""
    with ephemeral_postgres() as engine:
        adapter = FakeProviderAdapter()
        prepare(engine, adapter)

        def raw_insert(session: Session):
            session.add(
                ExternalAction(
                    reference=REFERENCE,
                    sequence=2,
                    provider="x",
                    operation="activate_ads",
                    idempotency_key="amz-raw-key",
                    provider_idempotent=True,
                    request_fingerprint="f" * 64,
                    status="PENDING",
                    correlation_id="c",
                )
            )
            session.commit()
            return "inserted"

        results = run_together(engine, [raw_insert])

        assert len(errors(results)) == 1
        assert "uq_external_actions_one_open_per_reference" in str(errors(results)[0])
