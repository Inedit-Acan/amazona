"""Tipos de cambio declarados a mano: cómo se eligen (Milestone 40)."""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.mock_exchange_rates import MockExchangeRateProvider
from app.db.base import Base
from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.money.manual import ManualExchangeRateProvider
from app.money.resolver import CompositeExchangeRateProvider
from app.sourcing.provenance import SupplierFactProvenance

TODAY = datetime.date(2026, 9, 29)


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


def declare(db: Session, **overrides) -> ExchangeRateRow:
    fields = {
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": Decimal("0.92"),
        "effective_date": TODAY,
        "source": "manual:owner",
        "provenance": "declared",
    }
    fields.update(overrides)
    row = ExchangeRateRow(**fields)
    db.add(row)
    db.commit()
    return row


def test_a_declared_rate_is_found(db_session):
    declare(db_session)

    rate = ManualExchangeRateProvider(db_session).rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.rate == Decimal("0.92")
    assert rate.provenance is SupplierFactProvenance.DECLARED


def test_nothing_declared_means_no_rate_not_a_default(db_session):
    assert ManualExchangeRateProvider(db_session).rate_for(base="USD", quote="EUR", on=TODAY) is None


def test_the_pair_is_found_in_either_direction(db_session):
    """Quien declaró `USD/EUR` no tiene que declarar además `EUR/USD`. Cuál se
    usó lo registra la conversión, porque invertir no es gratis."""
    declare(db_session)

    rate = ManualExchangeRateProvider(db_session).rate_for(base="EUR", quote="USD", on=TODAY)

    assert rate is not None
    assert rate.pair == "USD/EUR"


def test_the_most_recent_rate_not_later_than_the_date_wins(db_session):
    declare(db_session, rate=Decimal("0.90"), effective_date=datetime.date(2026, 9, 1))
    declare(db_session, rate=Decimal("0.95"), effective_date=datetime.date(2026, 9, 20))

    rate = ManualExchangeRateProvider(db_session).rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.rate == Decimal("0.95")


def test_a_rate_from_the_future_is_never_used(db_session):
    """Convertir septiembre con el cambio de octubre es mirar la respuesta antes
    de hacer el examen."""
    declare(db_session, rate=Decimal("0.90"), effective_date=datetime.date(2026, 9, 1))
    declare(db_session, rate=Decimal("0.99"), effective_date=datetime.date(2026, 10, 15))

    rate = ManualExchangeRateProvider(db_session).rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.rate == Decimal("0.90")


def test_a_third_party_rate_beats_a_declared_one_on_the_same_day(db_session):
    declare(db_session, rate=Decimal("0.90"))
    declare(
        db_session,
        rate=Decimal("0.93"),
        provenance="third_party_verified",
        declared_by="Banco de prueba",
        source="Banco de prueba",
    )

    rate = ManualExchangeRateProvider(db_session).rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.rate == Decimal("0.93")
    assert rate.declared_by == "Banco de prueba"


def test_a_declared_rate_is_preferred_over_the_fixture_one(db_session):
    """Lo que una persona ha declarado es un dato del mundo; el fixture no."""
    declare(db_session, rate=Decimal("0.80"))
    provider = CompositeExchangeRateProvider(
        [ManualExchangeRateProvider(db_session), MockExchangeRateProvider()]
    )

    rate = provider.rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.rate == Decimal("0.80")
    assert rate.provenance is SupplierFactProvenance.DECLARED


def test_the_fixture_rate_says_it_is_a_fixture(db_session):
    provider = CompositeExchangeRateProvider(
        [ManualExchangeRateProvider(db_session), MockExchangeRateProvider()]
    )

    rate = provider.rate_for(base="USD", quote="EUR", on=TODAY)

    assert rate is not None
    assert rate.provenance is SupplierFactProvenance.SIMULATED
    assert rate.source == "fixtures:mock-exchange-rates"


def test_a_pair_nobody_declared_has_no_rate_anywhere(db_session):
    provider = CompositeExchangeRateProvider(
        [ManualExchangeRateProvider(db_session), MockExchangeRateProvider()]
    )

    assert provider.rate_for(base="JPY", quote="EUR", on=TODAY) is None
