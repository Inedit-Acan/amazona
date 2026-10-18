"""El libro solo liquida sobre una reserva VIVA de ESA misma referencia (corrección del fallo «liquidar sin reserva»).

Antes, `record_commit` / `record_release` solo comprobaban que existiera un presupuesto: liquidaban aunque esa
referencia no se hubiera reservado nunca. Efectos medidos (con el mismo diagnóstico sobre `origin/main`):

- un `COMMIT` huérfano sumaba a `committed` y `spent` dinero que nadie reservó;
- un `RELEASE` huérfano restaba del agregado `reserved` y se llevaba la reserva viva de OTRA operación (el disponible se
  sobreestimaba);
- se podía liquidar más de lo reservado (`reserve 5` + `commit 8`) y comprometer una referencia que luego se reservaba.

Contrato (ADR 0026: una referencia se reserva una vez y se liquida una vez, comprometida O liberada):

- `outstanding(reference)` = lo reservado de ESA referencia menos lo que ya se liquidó de ella; `0` si nunca se reservó;
- sin reserva viva, `record_commit` / `record_release` NO escriben nada (ni evento, ni saldo) y devuelven `False`;
- con reserva viva, se liquida EXACTAMENTE lo reservado (una sola liquidación: una parcial dejaría un resto vivo que
  ninguna otra liquidación puede cerrar); otro importe es un `ValidationError` y no escribe nada;
- liquidar dos veces es un no-op (`False`), no una segunda liquidación: la restricción única de la base sigue ahí
  como respaldo.
"""

import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.budgets.service import BudgetLedgerService
from app.ceo.orchestrator import CEOOrchestrator
from app.core.errors import ValidationError
from app.db.base import Base
from app.db.models.approval import Approval
from app.db.models.audit import AuditLog
from app.db.models.budget import BudgetAllocation, FinancialEvent
from app.db.models.objective import Objective
from app.db.session import get_db
from app.main import app

A = "approval:A"
B = "approval:B"


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def engine(request):
    if request.param == "sqlite":
        sqlite = create_engine(
            "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(sqlite)
        yield sqlite
        sqlite.dispose()
    else:
        with ephemeral_postgres() as postgres:
            yield postgres


@pytest.fixture()
def factory(engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    return sessions


@pytest.fixture()
def budget(factory):
    with factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=100.0, actor="cli:test")
    return factory


def ledger_state(factory):
    with factory() as session:
        row = session.query(BudgetAllocation).first()
        saldo = None if row is None else (float(row.reserved), float(row.committed), float(row.spent))
        events = [
            (e.type, float(e.amount), e.reference)
            for e in session.query(FinancialEvent).order_by(FinancialEvent.created_at, FinancialEvent.id).all()
        ]
    return saldo, events


def run(factory, op: str, reference: str, amount: float):
    """Una operación en su propia sesión y su propio commit, como en la API."""
    with factory() as session:
        service = BudgetLedgerService(session)
        result = {
            "reserve": service.reserve,
            "commit": service.record_commit,
            "release": service.record_release,
        }[op](amount=amount, reference=reference)
        session.commit()
        return result


def outstanding(factory, reference: str):
    with factory() as session:
        return BudgetLedgerService(session).outstanding(reference)


# --- A, B: liquidar SIN reserva -------------------------------------------------------------------------------


def test_a_commit_without_a_reservation_is_refused_and_writes_nothing(budget):
    assert run(budget, "commit", A, 5.0) is False
    assert ledger_state(budget) == ((0.0, 0.0, 0.0), [])


def test_a_release_without_a_reservation_is_refused_and_writes_nothing(budget):
    assert run(budget, "release", A, 5.0) is False
    assert ledger_state(budget) == ((0.0, 0.0, 0.0), [])


def test_without_an_authorised_budget_nothing_moves_either(factory):
    assert run(factory, "commit", A, 5.0) is False
    assert run(factory, "release", A, 5.0) is False
    assert ledger_state(factory) == (None, [])


# --- C, D, K: nunca se toca la reserva de OTRA referencia -----------------------------------------------------


def test_committing_b_without_its_own_reservation_does_not_consume_the_reservation_of_a(budget):
    run(budget, "reserve", A, 10.0)
    assert run(budget, "commit", B, 5.0) is False
    assert ledger_state(budget) == ((10.0, 0.0, 0.0), [("RESERVE", 10.0, A)])
    assert outstanding(budget, A) == 10


def test_releasing_b_without_its_own_reservation_does_not_consume_the_reservation_of_a(budget):
    run(budget, "reserve", A, 10.0)
    assert run(budget, "release", B, 5.0) is False
    assert ledger_state(budget) == ((10.0, 0.0, 0.0), [("RESERVE", 10.0, A)])
    # el disponible NO se sobreestima: 100 - 10 reservados = 90
    saldo, _ = ledger_state(budget)
    assert 100.0 - saldo[0] - saldo[1] == 90.0


def test_an_orphan_settlement_with_a_live_reservation_of_another_operation_changes_nothing(budget):
    run(budget, "reserve", A, 10.0)
    before = ledger_state(budget)
    for op in ("commit", "release"):
        for amount in (1.0, 10.0, 999.0):
            assert run(budget, op, "approval:ninguna", amount) is False
    assert ledger_state(budget) == before


# --- E, F: el camino normal -----------------------------------------------------------------------------------


def test_reserve_then_commit_the_same_amount_commits_it(budget):
    run(budget, "reserve", A, 10.0)
    assert run(budget, "commit", A, 10.0) is True
    assert ledger_state(budget) == ((0.0, 10.0, 10.0), [("RESERVE", 10.0, A), ("COMMIT", 10.0, A)])
    assert outstanding(budget, A) == 0


def test_reserve_then_release_the_same_amount_releases_it(budget):
    run(budget, "reserve", A, 10.0)
    assert run(budget, "release", A, 10.0) is True
    assert ledger_state(budget) == ((0.0, 0.0, 0.0), [("RESERVE", 10.0, A), ("RELEASE", 10.0, A)])
    assert outstanding(budget, A) == 0


def test_two_independent_operations_settle_independently(budget):
    run(budget, "reserve", A, 10.0)
    run(budget, "reserve", B, 20.0)
    assert run(budget, "commit", A, 10.0) is True
    assert run(budget, "release", B, 20.0) is True
    assert ledger_state(budget)[0] == (0.0, 10.0, 10.0)


# --- G: el importe --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["commit", "release"])
@pytest.mark.parametrize("amount", [15.0, 10.01, 9.99, 5.0, 0.01])
def test_settling_an_amount_different_from_the_reservation_is_refused_and_writes_nothing(budget, op, amount):
    run(budget, "reserve", A, 10.0)
    before = ledger_state(budget)
    with pytest.raises(ValidationError):
        run(budget, op, A, amount)
    assert ledger_state(budget) == before, "un importe distinto no escribe nada"
    assert outstanding(budget, A) == 10, "y la reserva sigue viva"
    assert run(budget, op, A, 10.0) is True, "el importe exacto sigue pudiendo liquidarla"


# --- H, I: ya liquidada ---------------------------------------------------------------------------------------


def test_a_reservation_already_committed_cannot_be_settled_again(budget):
    run(budget, "reserve", A, 10.0)
    run(budget, "commit", A, 10.0)
    before = ledger_state(budget)
    assert run(budget, "commit", A, 10.0) is False
    assert run(budget, "release", A, 10.0) is False
    assert ledger_state(budget) == before


def test_a_reservation_already_released_cannot_be_settled_again(budget):
    run(budget, "reserve", A, 10.0)
    run(budget, "release", A, 10.0)
    before = ledger_state(budget)
    assert run(budget, "release", A, 10.0) is False
    assert run(budget, "commit", A, 10.0) is False
    assert ledger_state(budget) == before


# --- J: commit huérfano seguido de reserva --------------------------------------------------------------------


def test_an_orphan_commit_does_not_exist_so_a_later_reservation_starts_clean(budget):
    assert run(budget, "commit", A, 5.0) is False
    assert run(budget, "reserve", A, 5.0) is True
    assert ledger_state(budget) == ((5.0, 0.0, 0.0), [("RESERVE", 5.0, A)])
    assert outstanding(budget, A) == 5


# --- outstanding ----------------------------------------------------------------------------------------------


def test_outstanding_is_per_reference_and_zero_when_never_reserved_or_already_settled(budget):
    assert outstanding(budget, A) == 0, "nunca reservada"
    run(budget, "reserve", A, 7.0)
    run(budget, "reserve", B, 3.0)
    assert outstanding(budget, A) == 7 and outstanding(budget, B) == 3, "no es el total global (10)"
    run(budget, "commit", A, 7.0)
    assert outstanding(budget, A) == 0, "comprometida"
    run(budget, "release", B, 3.0)
    assert outstanding(budget, B) == 0, "liberada"


# --- L, M, N: las aprobaciones (aprobar, rechazar, caducar) ---------------------------------------------------

SPEND = {
    "product_validation": {"estimated_monthly_searches": 12000, "competition_level": "low"},
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
    "requests_simulated_spend": True,
    "spend_action": "simulated_external_spend",
    "spend_amount": 1.0,
}


@pytest.fixture()
def client(factory):
    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def mission(factory, *, with_budget: bool) -> str:
    """El flujo REAL del CEO. Sin presupuesto autorizado en un despliegue simulado, el gasto se aprueba sin reserva."""
    with factory() as session:
        if with_budget:
            BudgetLedgerService(session).authorise_budget(hard_limit=100.0, actor="cli:test")
        objective = Objective(title="[PRUEBA] ledger", created_by="prueba", context=SPEND)
        session.add(objective)
        session.commit()
        CEOOrchestrator(session).run_objective(objective.id)
        session.commit()
        return session.query(Approval).order_by(Approval.requested_at.desc()).first().id


def effect(client, approval_id: str) -> str:
    return {row["id"]: row for row in client.get("/api/approvals").json()}[approval_id]["budget_effect"]


@pytest.mark.parametrize("verb,status", [("approve", "APPROVED"), ("reject", "REJECTED")])
def test_an_approval_requested_without_a_budget_moves_no_money_even_if_a_budget_is_authorised_later(
    client, factory, verb, status
):
    approval_id = mission(factory, with_budget=False)
    assert ledger_state(factory) == (None, [])
    with factory() as session:  # el propietario autoriza un presupuesto DESPUÉS de pedirse la aprobación
        BudgetLedgerService(session).authorise_budget(hard_limit=100.0, actor="cli:test")
    response = client.post(f"/api/approvals/{approval_id}/{verb}", json={})
    assert response.status_code == 200
    assert response.json()["status"] == status, "la resolución humana sigue funcionando sin reserva"
    assert response.json()["budget_effect"] == "none", "pero no hay movimiento financiero"
    assert ledger_state(factory) == ((0.0, 0.0, 0.0), [])


def test_an_approval_without_a_reservation_that_expires_releases_nothing(client, factory):
    approval_id = mission(factory, with_budget=False)
    with factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=100.0, actor="cli:test")
        session.get(Approval, approval_id).expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            hours=1
        )
        session.commit()
    response = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.status_code == 409, "vencida: ya no se puede resolver"
    with factory() as session:
        assert session.get(Approval, approval_id).status == "EXPIRED", "el estado SÍ cambia"
        assert session.query(AuditLog).filter_by(action="approval.expire").count() == 1
    assert ledger_state(factory) == ((0.0, 0.0, 0.0), []), "sin reserva, la caducidad no libera nada"
    assert effect(client, approval_id) == "none"


def test_an_approval_with_a_reservation_that_expires_releases_exactly_its_reservation(client, factory):
    approval_id = mission(factory, with_budget=True)
    assert ledger_state(factory)[0] == (1.0, 0.0, 0.0)
    with factory() as session:
        session.get(Approval, approval_id).expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            hours=1
        )
        session.commit()
    assert client.post(f"/api/approvals/{approval_id}/approve", json={}).status_code == 409
    assert ledger_state(factory)[0] == (0.0, 0.0, 0.0)
    assert effect(client, approval_id) == "released"


@pytest.mark.parametrize(
    "verb,expected,saldo", [("approve", "committed", (0.0, 1.0, 1.0)), ("reject", "released", (0.0, 0.0, 0.0))]
)
def test_an_approval_with_a_reservation_still_commits_or_releases_it(client, factory, verb, expected, saldo):
    approval_id = mission(factory, with_budget=True)
    assert effect(client, approval_id) == "reserved"
    response = client.post(f"/api/approvals/{approval_id}/{verb}", json={})
    assert response.status_code == 200
    assert response.json()["budget_effect"] == expected
    assert ledger_state(factory)[0] == saldo


def test_resolving_an_unreserved_approval_does_not_consume_the_reservation_of_another(client, factory):
    unreserved = mission(factory, with_budget=False)  # sin reserva
    with factory() as session:
        BudgetLedgerService(session).authorise_budget(hard_limit=100.0, actor="cli:test")
    reserved = mission(factory, with_budget=True)  # con reserva de 1
    assert ledger_state(factory)[0] == (1.0, 0.0, 0.0)
    assert client.post(f"/api/approvals/{unreserved}/reject", json={}).status_code == 200
    assert ledger_state(factory)[0] == (1.0, 0.0, 0.0), "rechazar la aprobación SIN reserva no libera la de la otra"
    assert effect(client, reserved) == "reserved"
    assert client.post(f"/api/approvals/{unreserved}/approve", json={}).status_code == 409  # ya resuelta
    assert ledger_state(factory)[0] == (1.0, 0.0, 0.0)


# --- Concurrencia (PostgreSQL: dos conexiones de verdad) ------------------------------------------------------


def together(engine, jobs):
    """Lanza los trabajos a la vez (una conexión cada uno) y devuelve sus resultados o la clase de su excepción."""
    barrier = threading.Barrier(len(jobs))
    results: list[object] = [None] * len(jobs)

    def go(index: int):
        try:
            with Session(engine) as session:
                barrier.wait(timeout=30)
                results[index] = jobs[index](session)
                session.commit()
        except Exception as exc:  # noqa: BLE001 - se observa
            results[index] = f"EXC:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(go, range(len(jobs))))
    return results


@pytest.fixture()
def pg():
    with ephemeral_postgres() as postgres:
        with Session(postgres) as session:
            BudgetLedgerService(session).authorise_budget(hard_limit=1000.0, actor="cli:test")
        yield postgres


def reset_ledger(pg):
    with Session(pg) as session:
        session.query(FinancialEvent).delete()
        row = session.query(BudgetAllocation).one()
        row.reserved = row.committed = row.spent = 0
        session.commit()


def pg_state(pg):
    return ledger_state(sessionmaker(bind=pg, expire_on_commit=False))


def commit_job(reference, amount):
    return lambda s: BudgetLedgerService(s).record_commit(amount=amount, reference=reference)


def release_job(reference, amount):
    return lambda s: BudgetLedgerService(s).record_release(amount=amount, reference=reference)


def test_two_simultaneous_commits_of_the_same_reservation_commit_it_once(pg):
    for _ in range(5):
        reset_ledger(pg)
        with Session(pg) as session:
            assert BudgetLedgerService(session).reserve(amount=10.0, reference=A)
            session.commit()
        results = together(pg, [commit_job(A, 10.0), commit_job(A, 10.0)])
        assert sorted(map(str, results)) == ["False", "True"], results
        assert pg_state(pg) == ((0.0, 10.0, 10.0), [("RESERVE", 10.0, A), ("COMMIT", 10.0, A)])


def test_a_commit_and_a_release_at_the_same_time_settle_the_reservation_once(pg):
    for _ in range(5):
        reset_ledger(pg)
        with Session(pg) as session:
            assert BudgetLedgerService(session).reserve(amount=10.0, reference=A)
            session.commit()
        results = together(pg, [commit_job(A, 10.0), release_job(A, 10.0)])
        assert sorted(map(str, results)) == ["False", "True"], results
        saldo, events = pg_state(pg)
        assert len(events) == 2 and events[0][0] == "RESERVE" and events[1][0] in ("COMMIT", "RELEASE")
        assert saldo in ((0.0, 10.0, 10.0), (0.0, 0.0, 0.0)), "no se cuenta dos veces ni se queda a medias"


def test_many_simultaneous_orphan_settlements_never_touch_a_live_reservation(pg):
    reset_ledger(pg)
    with Session(pg) as session:
        assert BudgetLedgerService(session).reserve(amount=10.0, reference=A)
        session.commit()
    jobs = [commit_job(f"approval:x{i}", 5.0) if i % 2 else release_job(f"approval:x{i}", 5.0) for i in range(8)]
    assert together(pg, jobs) == [False] * 8
    assert pg_state(pg) == ((10.0, 0.0, 0.0), [("RESERVE", 10.0, A)])


def test_a_reservation_and_a_commit_of_the_same_reference_at_the_same_time_never_leave_an_orphan(pg):
    for trial in range(8):
        reset_ledger(pg)
        reference = f"approval:r{trial}"
        reserve_job = lambda s, ref=reference: BudgetLedgerService(s).reserve(amount=10.0, reference=ref)  # noqa: E731
        results = together(pg, [reserve_job, commit_job(reference, 10.0)])
        saldo, events = pg_state(pg)
        assert results[0] is True
        if results[1] is True:  # el commit llegó con la reserva ya visible
            assert events == [("RESERVE", 10.0, reference), ("COMMIT", 10.0, reference)]
            assert saldo == (0.0, 10.0, 10.0)
        else:  # llegó antes: no hay nada que liquidar y NO queda un commit huérfano
            assert results[1] is False
            assert events == [("RESERVE", 10.0, reference)]
            assert saldo == (10.0, 0.0, 0.0)


def test_the_database_still_refuses_a_second_settlement_if_a_path_skips_the_ledger_guard(pg):
    """El índice único de liquidación (ADR 0026) sigue siendo el respaldo si un camino se salta la guarda."""
    reset_ledger(pg)
    with Session(pg) as session:
        assert BudgetLedgerService(session).reserve(amount=10.0, reference=A)
        session.add(FinancialEvent(type="COMMIT", amount=10.0, reference=A))
        session.commit()
    with Session(pg) as session:
        session.add(FinancialEvent(type="RELEASE", amount=10.0, reference=A))
        with pytest.raises(Exception, match="uq_financial_events_one_settlement_per_reference"):
            session.commit()


def test_a_settlement_without_a_reservation_does_not_wait_for_an_unrelated_settlement_in_flight(pg):
    """Las liquidaciones se ordenan POR REFERENCIA: una que va a ser un no-op (no hay reserva viva) no espera a la
    liquidación de OTRA referencia que sigue en vuelo. Con un lock común para todas las referencias, la primera
    quedaría bloqueada hasta que la ajena confirme (los resultados serían los mismos; cambiaría la espera).
    Sincronización con eventos, sin `sleep`: la ventana de 10 s solo es el margen para un fallo; con el código
    correcto termina en milisegundos."""
    reset_ledger(pg)
    with Session(pg) as session:
        assert BudgetLedgerService(session).reserve(amount=5.0, reference=A)
        session.commit()

    in_flight = Session(pg)  # la liquidación de A está ejecutada y SIN confirmar: sostiene sus bloqueos
    assert BudgetLedgerService(in_flight).record_commit(amount=5.0, reference=A) is True

    done = threading.Event()
    outcome: dict[str, object] = {}

    def settle_an_unreserved_reference() -> None:
        try:
            with Session(pg) as other:
                outcome["result"] = BudgetLedgerService(other).record_commit(
                    amount=5.0, reference="approval:sin-reserva"
                )
                other.commit()
        except Exception as exc:  # noqa: BLE001 - se observa
            outcome["result"] = f"EXC:{type(exc).__name__}"
        finally:
            done.set()

    worker = threading.Thread(target=settle_an_unreserved_reference)
    worker.start()
    try:
        finished_while_the_other_is_still_open = done.wait(timeout=10.0)
        assert finished_while_the_other_is_still_open, "esperó a una liquidación ajena: el lock no es por referencia"
        assert outcome["result"] is False, "sin reserva viva es un no-op"
    finally:
        in_flight.commit()  # suelta los bloqueos de A (también si la comprobación falló, para no dejar el hilo colgado)
        in_flight.close()
        worker.join(timeout=30)
    assert pg_state(pg) == ((0.0, 5.0, 5.0), [("RESERVE", 5.0, A), ("COMMIT", 5.0, A)]), "solo A se liquidó"
