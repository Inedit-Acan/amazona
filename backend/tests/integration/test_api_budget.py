"""`GET /api/budget`: el presupuesto operativo, solo para verlo (M47).

Lo que se fija: las cifras salen de las filas y no de otra cuenta; «no hay presupuesto» es un hecho y no un error ni
un cero; `remaining` es lo que el motor llama disponible (`hard_limit − reserved − committed`, sin restar `spent`);
leer no escribe nada ni crea nada; y la ruta no admite ninguna escritura.
"""

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.budgets.service import BudgetLedgerService
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation, FinancialEvent
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture()
def client(factory) -> TestClient:
    return TestClient(app)


class _ConfirmedLedger:
    """El libro de la prueba: cada movimiento se confirma al terminar, como lo haría una petición. Sin eso, lo escrito
    quedaría en una transacción abierta y la lectura de la ruta (otra sesión) no lo vería de forma fiable."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._ledger = BudgetLedgerService(session)

    def __getattr__(self, name: str):
        method = getattr(self._ledger, name)

        def call(*args, **kwargs):
            result = method(*args, **kwargs)
            self._session.commit()
            return result

        return call


def _ledger(factory, *, hard_limit: float = 100.0, soft_limit: float | None = None) -> _ConfirmedLedger:
    ledger = _ConfirmedLedger(factory())
    ledger.authorise_budget(hard_limit=hard_limit, soft_limit=soft_limit, actor="test")
    return ledger


def _balance(budget: dict) -> tuple[str, str, str, str]:
    return budget["reserved"], budget["committed"], budget["spent"], budget["remaining"]


def _counts(factory) -> tuple[int, int, int, int]:
    with factory() as db:
        models = (Budget, BudgetAllocation, FinancialEvent, AuditLog)
        budgets, allocations, events, audits = (db.scalar(select(func.count()).select_from(model)) for model in models)
        return budgets or 0, allocations or 0, events or 0, audits or 0


def test_without_an_authorised_budget_it_says_so_and_invents_none(client, factory):
    response = client.get("/api/budget")

    assert response.status_code == 200
    body = response.json()
    assert body["authorised"] is False
    assert body["budget"] is None
    assert _counts(factory) == (0, 0, 0, 0)  # leer no crea el presupuesto, ni su saldo, ni una auditoría


def test_a_fresh_budget_is_all_available(client, factory):
    _ledger(factory, hard_limit=100.0)

    body = client.get("/api/budget").json()

    assert body["authorised"] is True
    budget = body["budget"]
    assert (budget["hard_limit"], budget["reserved"], budget["committed"], budget["spent"], budget["remaining"]) == (
        "100.00",
        "0.00",
        "0.00",
        "0.00",
        "100.00",
    )
    assert budget["soft_limit"] is None
    assert budget["name"] == "orchestrator-default"
    assert budget["period"] == "monthly"


def test_a_reservation_is_reserved_and_lowers_what_remains(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=25.0, reference="approval:a")

    budget = client.get("/api/budget").json()["budget"]

    assert _balance(budget) == ("25.00", "0.00", "0.00", "75.00")


def test_a_commit_moves_the_reservation_to_committed_and_spent_without_counting_it_twice(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=40.0, reference="approval:a")
    assert ledger.record_commit(amount=40.0, reference="approval:a")

    budget = client.get("/api/budget").json()["budget"]

    # Disponible = techo − reservado − comprometido. `spent` (40) NO se resta otra vez: sería 20 y contaría el gasto
    # dos veces.
    assert _balance(budget) == ("0.00", "40.00", "40.00", "60.00")


def test_a_release_gives_the_reservation_back(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=30.0, reference="approval:a")
    assert ledger.record_release(amount=30.0, reference="approval:a")

    budget = client.get("/api/budget").json()["budget"]

    assert _balance(budget) == ("0.00", "0.00", "0.00", "100.00")


def test_a_budget_used_up_has_zero_remaining(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=100.0, reference="approval:a")

    budget = client.get("/api/budget").json()["budget"]

    assert budget["remaining"] == "0.00"
    assert budget["hard_limit"] == "100.00"


def test_a_reservation_and_a_commit_add_up_in_what_remains(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=40.0, reference="approval:a")
    assert ledger.record_commit(amount=40.0, reference="approval:a")
    assert ledger.reserve(amount=25.0, reference="approval:b")

    budget = client.get("/api/budget").json()["budget"]

    assert _balance(budget) == ("25.00", "40.00", "40.00", "35.00")


def test_the_soft_limit_is_shown_when_there_is_one(client, factory):
    _ledger(factory, hard_limit=100.0, soft_limit=80.0)

    budget = client.get("/api/budget").json()["budget"]

    assert (budget["hard_limit"], budget["soft_limit"]) == ("100.00", "80.00")


def test_the_currency_is_the_accounting_currency_and_says_where_it_comes_from(client, factory):
    _ledger(factory)

    budget = client.get("/api/budget").json()["budget"]

    # `budgets` no tiene columna de moneda: la moneda es el contrato contable, y la respuesta dice que lo es.
    assert budget["currency"] == "EUR"
    assert budget["currency_source"] == "accounting_currency"


def test_a_budget_without_a_balance_row_reads_as_nothing_moved_and_creates_none(client, factory):
    with factory() as db:
        db.add(Budget(name="orchestrator-default", hard_limit=50.0))
        db.commit()
    before = _counts(factory)

    budget = client.get("/api/budget").json()["budget"]

    assert _balance(budget) == ("0.00", "0.00", "0.00", "50.00")
    assert _counts(factory) == before == (1, 0, 0, 0)


def test_a_desynchronised_balance_shows_a_negative_remaining_instead_of_hiding_it(client, factory):
    _ledger(factory)
    with factory() as db:
        allocation = db.query(BudgetAllocation).one()
        allocation.committed = 130.0  # un saldo que ya no cuadra con el techo
        db.commit()

    budget = client.get("/api/budget").json()["budget"]

    assert budget["remaining"] == "-30.00"


def test_each_figure_comes_from_its_own_column(client, factory):
    """Hoy lo gastado y lo comprometido se mueven juntos, y una lectura que confundiera una con otra pasaría
    desapercibida. Con las tres cifras distintas (y un periodo y un umbral que no son los de por defecto) cada una
    tiene que salir de la suya."""
    _ledger(factory, hard_limit=100.0)
    with factory() as db:
        budget = db.query(Budget).one()
        budget.period = "weekly"
        budget.soft_limit = 70.0
        allocation = db.query(BudgetAllocation).one()
        allocation.reserved = 5.0
        allocation.committed = 10.0
        allocation.spent = 7.0
        db.commit()

    budget = client.get("/api/budget").json()["budget"]

    assert (budget["reserved"], budget["committed"], budget["spent"]) == ("5.00", "10.00", "7.00")
    assert budget["remaining"] == "85.00"  # 100 − 5 − 10: lo gastado (7) no se resta
    assert (budget["period"], budget["soft_limit"]) == ("weekly", "70.00")


def _statements_of(factory, request) -> list[str]:
    """Todas las sentencias SQL que ejecuta `request()` (un `GET`), para comprobar que la lectura solo lee."""
    engine = factory.kw["bind"]
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement.strip())

    event.listen(engine, "before_cursor_execute", record)
    try:
        request()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return seen


@pytest.mark.parametrize("with_balance", [True, False])
def test_the_read_runs_only_selects(client, factory, with_balance):
    """Que una escritura se deshaga al cerrar la sesión no la hace una lectura: el `GET` no ejecuta ningún INSERT,
    UPDATE ni DELETE (ni siquiera uno que luego se desharía, como crear el saldo que falta)."""
    if with_balance:
        ledger = _ledger(factory)
        assert ledger.reserve(amount=25.0, reference="approval:a")
    else:
        with factory() as db:
            db.add(Budget(name="orchestrator-default", hard_limit=50.0))
            db.commit()

    statements = _statements_of(factory, lambda: client.get("/api/budget"))

    assert statements, "la lectura no ejecutó nada"
    assert all(statement.upper().startswith("SELECT") for statement in statements), statements


def test_money_is_always_written_as_exact_cents():
    """`_money` es el único sitio que fija los céntimos del texto que sale. Las columnas `Numeric(12, 2)` ya devuelven
    dos decimales (SQLAlchemy los formatea al leer), así que por la ruta esto no se ve; si mañana la columna cambiara
    de escala, el texto seguiría siendo de céntimos exactos y no de lo que la base devuelva."""
    from decimal import Decimal

    from app.budgets.service import _money

    assert [str(_money(value)) for value in (5, 7.5, "7.5", Decimal("100"), 0.1 + 0.2, Decimal("1.0000"))] == [
        "5.00",
        "7.50",
        "7.50",
        "100.00",
        "0.30",
        "1.00",
    ]


def test_amounts_are_exact_cents_even_when_the_stored_value_is_a_float(client, factory):
    with factory() as db:
        db.add(Budget(name="orchestrator-default", hard_limit=0.1 + 0.2))
        db.commit()

    budget = client.get("/api/budget").json()["budget"]

    assert (budget["hard_limit"], budget["remaining"]) == ("0.30", "0.30")


def test_reading_writes_nothing_and_is_repeatable(client, factory):
    ledger = _ledger(factory)
    assert ledger.reserve(amount=25.0, reference="approval:a")
    before = _counts(factory)

    first = client.get("/api/budget").json()
    second = client.get("/api/budget").json()

    assert _counts(factory) == before
    assert first["budget"] == second["budget"]


def test_read_at_is_a_utc_instant(client, factory):
    _ledger(factory)
    before = datetime.datetime.now(datetime.UTC)

    stamp = client.get("/api/budget").json()["read_at"]

    read_at = datetime.datetime.fromisoformat(stamp)
    assert read_at.utcoffset() == datetime.timedelta(0)
    assert before <= read_at <= datetime.datetime.now(datetime.UTC)


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_the_route_admits_no_write(client, method):
    assert getattr(client, method)("/api/budget").status_code == 405
