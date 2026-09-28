"""El contador de llamadas externas, contra base de datos (Milestone 37, §25).

Lo que se comprueba aquí y no en la función pura: que **queda fila pase lo que
pase**, que lo consumido se lee de esas filas, y que una denegación corta la
llamada en vez de dejarla pasar «solo esta vez».
"""

import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.costs.policy import SpendLimit
from app.costs.service import ApiBudgetExceededError, CostMeter, UnmeteredCalls
from app.db.base import Base
from app.db.models.external_api_cost import ExternalApiCost

FREE_PROVIDER = "wikimedia-pageviews"
EBAY = "ebay-browse"
UNWRITTEN = "un-proveedor-sin-politica"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def meter(db: Session, *, correlation_id: str = "cid-1", limits=None) -> CostMeter:
    return CostMeter(db, correlation_id=correlation_id, limits=limits or {})


def costs(db: Session) -> list[ExternalApiCost]:
    return db.query(ExternalApiCost).order_by(ExternalApiCost.created_at).all()


# --- Lo que se apunta -------------------------------------------------------


def test_an_allowed_call_leaves_its_row(db_session: Session):
    meter(db_session).authorise(provider=FREE_PROVIDER, operation="pageviews", units=1)

    [row] = costs(db_session)
    assert row.provider == FREE_PROVIDER
    assert row.operation == "pageviews"
    assert row.units == 1
    assert row.unit == "requests"
    assert row.outcome == "allowed"
    assert row.estimated_cost == 0.0
    assert row.currency == "EUR"
    assert row.correlation_id == "cid-1"


def test_the_real_cost_is_absent_not_zero(db_session: Session):
    """Nulo significa que el proveedor todavía no ha dicho lo que cobró."""
    meter(db_session).authorise(provider=FREE_PROVIDER, operation="pageviews")

    [row] = costs(db_session)
    assert row.actual_cost is None


def test_a_denied_call_also_leaves_its_row_and_says_why(db_session: Session):
    """Es la fila que explica por qué una investigación volvió sin señales."""
    with pytest.raises(ApiBudgetExceededError):
        meter(db_session).authorise(provider=UNWRITTEN, operation="lo-que-sea")

    [row] = costs(db_session)
    assert row.outcome == "denied"
    assert row.denied_reason
    assert "límite de gasto autorizado" in row.denied_reason


def test_a_denial_stops_the_caller_instead_of_letting_it_through(db_session: Session):
    with pytest.raises(ApiBudgetExceededError):
        meter(db_session).authorise(provider=UNWRITTEN, operation="lo-que-sea")


# --- Lo consumido -----------------------------------------------------------


def test_what_was_spent_today_comes_from_the_rows(db_session: Session):
    counter = meter(db_session)
    for _ in range(5):
        counter.authorise(provider=EBAY, operation="item_summary/search")

    assert len(costs(db_session)) == 5


def test_the_daily_quota_is_enforced_from_the_ledger(db_session: Session):
    """eBay publica 5.000 llamadas al día. Se cuentan las de las filas, no una
    variable en memoria que se pierde al reiniciar el proceso."""
    limits = {EBAY: SpendLimit(provider=EBAY, currency="EUR", max_units_per_day=3)}
    counter = meter(db_session, limits=limits)
    for _ in range(3):
        counter.authorise(provider=EBAY, operation="item_summary/search")

    with pytest.raises(ApiBudgetExceededError):
        counter.authorise(provider=EBAY, operation="item_summary/search")


def test_a_denied_call_consumes_nothing(db_session: Session):
    """Una llamada que no se hizo no gastó cuota de nadie."""
    limits = {EBAY: SpendLimit(provider=EBAY, currency="EUR", max_units_per_day=1)}
    counter = meter(db_session, limits=limits)
    counter.authorise(provider=EBAY, operation="item_summary/search")
    with pytest.raises(ApiBudgetExceededError):
        counter.authorise(provider=EBAY, operation="item_summary/search")

    allowed = [row for row in costs(db_session) if row.outcome == "allowed"]
    assert len(allowed) == 1


def test_the_run_cap_is_scoped_to_its_correlation_id(db_session: Session):
    """Otra ejecución empieza con su propio contador por ejecución."""
    first = meter(db_session, correlation_id="cid-a")
    for _ in range(8):
        first.authorise(provider=FREE_PROVIDER, operation="pageviews")
    with pytest.raises(ApiBudgetExceededError):
        first.authorise(provider=FREE_PROVIDER, operation="pageviews")

    second = meter(db_session, correlation_id="cid-b")
    second.authorise(provider=FREE_PROVIDER, operation="pageviews")

    assert len([row for row in costs(db_session) if row.correlation_id == "cid-b"]) == 1


def test_yesterdays_spending_does_not_count_against_today(db_session: Session):
    limits = {EBAY: SpendLimit(provider=EBAY, currency="EUR", max_units_per_day=1)}
    yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    db_session.add(
        ExternalApiCost(
            provider=EBAY,
            operation="item_summary/search",
            units=5,
            unit="requests",
            estimated_cost=0.0,
            actual_cost=None,
            currency="EUR",
            outcome="allowed",
            denied_reason=None,
            correlation_id="cid-old",
            observed_at=yesterday,
        )
    )
    db_session.commit()

    meter(db_session, limits=limits).authorise(provider=EBAY, operation="item_summary/search")

    assert len([row for row in costs(db_session) if row.outcome == "allowed"]) == 2


# --- El contador de mentira -------------------------------------------------


def test_the_unmetered_counter_allows_everything_and_records_nothing(db_session: Session):
    """Existe solo para probar un adaptador en aislamiento. Si apareciera en
    producción, las llamadas se harían sin techo y sin registro."""
    UnmeteredCalls().authorise(provider=UNWRITTEN, operation="lo-que-sea", units=999)

    assert costs(db_session) == []
