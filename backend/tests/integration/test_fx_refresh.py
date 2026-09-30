"""El refresco de las referencias del BCE y su lectura (Milestone 42, ADR 0020).

Cubre la identidad de una observación, la republicación, el todo o nada, el
histórico como recuperación explícita, la precedencia manual > BCE > mock y la
antigüedad. La fuente se sustituye por una falsa: ninguna prueba toca la red.
"""

import datetime
from decimal import Decimal

import pytest
from ecb_test_support import (
    ADMITTED,
    OMITTED,
    REAL_RATES,
    FakeFeed,
    rate_set,
    real_settings,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.costs.service import ApiBudgetExceededError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.exchange_rate import ExchangeRate as Row
from app.integrations.fx.ecb import FeedUnavailableError
from app.money.ecb import ECB_SOURCE, ISSUER, EcbExchangeRateProvider
from app.money.fx_refresh import FxRefreshService, FxSourceNotConfiguredError
from app.money.manual import ManualExchangeRateProvider
from app.money.money import Money
from app.money.rates import StaleRateError, convert
from app.money.resolver import exchange_rates_for

TODAY = datetime.datetime.now(datetime.UTC).date()
YESTERDAY = TODAY - datetime.timedelta(days=1)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def service(db: Session, feed: FakeFeed, settings: Settings | None = None) -> FxRefreshService:
    return FxRefreshService(db, settings or real_settings(), feed=feed)


def count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Row))


def ecb_rows(db: Session, quote: str = "USD") -> list[Row]:
    return (
        db.query(Row)
        .filter(Row.source == ECB_SOURCE, Row.quote_currency == quote)
        .order_by(Row.created_at)
        .all()
    )


def actions(db: Session) -> list[str]:
    return [row.action for row in db.query(AuditLog).order_by(AuditLog.created_at).all()]


# --- Qué se guarda y con qué -------------------------------------------------


def test_a_daily_refresh_stores_only_the_currencies_the_catalogue_admits(db):
    result = service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    stored = {row.quote_currency for row in db.query(Row).all()}
    assert stored == ADMITTED
    assert result.stored == len(ADMITTED)
    assert result.unchanged == 0
    assert result.republished == []
    # Lo que el BCE publica y no admitimos se lista; no entra ni se añade al catálogo.
    assert result.omitted_currencies == OMITTED


def test_an_observation_keeps_source_effective_date_ingestion_date_and_provenance(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    (row,) = ecb_rows(db, "USD")
    assert row.base_currency == "EUR"
    assert row.quote_currency == "USD"
    assert row.rate == REAL_RATES["USD"]
    assert row.source == ECB_SOURCE
    assert row.effective_date == YESTERDAY
    assert row.provenance == "third_party_verified"
    assert row.declared_by == ISSUER
    assert row.created_at is not None
    assert "eurofxref-daily" in row.note


def test_the_ingestion_date_is_not_the_effective_date(db):
    """Una tasa del viernes ingerida el lunes: la fecha efectiva es la del viernes."""
    friday = TODAY - datetime.timedelta(days=3)
    service(db, FakeFeed(daily=rate_set(friday))).refresh_daily(actor="owner")

    (row,) = ecb_rows(db, "USD")
    assert row.effective_date == friday
    assert row.created_at.date() >= TODAY - datetime.timedelta(days=1)


def test_the_result_reports_the_source_date_not_todays(db):
    result = service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    assert result.latest_effective_date == YESTERDAY
    assert result.mode == "daily"
    assert result.days_examined == 1


# --- Idempotencia y republicación ---------------------------------------------


def test_the_same_observation_twice_is_not_duplicated(db):
    feed = FakeFeed(daily=rate_set(YESTERDAY))
    service(db, feed).refresh_daily(actor="owner")
    first = count(db)

    again = service(db, feed).refresh_daily(actor="owner")

    assert count(db) == first
    assert again.stored == 0
    assert again.unchanged == len(ADMITTED)
    assert again.republished == []


def test_a_different_rate_for_the_same_pair_and_date_is_kept_beside_the_first_and_wins(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    republished = dict(REAL_RATES, USD=Decimal("1.1400"))

    result = service(db, FakeFeed(daily=rate_set(YESTERDAY, republished))).refresh_daily(
        actor="owner"
    )

    rows = ecb_rows(db, "USD")
    assert [row.rate for row in rows] == [Decimal("1.1355"), Decimal("1.1400")]
    assert result.stored == 0
    assert result.unchanged == len(ADMITTED) - 1
    (item,) = result.republished
    assert (item.pair, item.previous_rate, item.new_rate) == ("EUR/USD", Decimal("1.1355"), Decimal("1.1400"))
    # La más reciente gana al leer.
    chosen = EcbExchangeRateProvider(db).rate_for(base="EUR", quote="USD", on=TODAY)
    assert chosen.rate == Decimal("1.1400")


def test_a_republication_is_audited_with_both_values(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    service(db, FakeFeed(daily=rate_set(YESTERDAY, dict(REAL_RATES, USD=Decimal("1.1400"))))).refresh_daily(
        actor="owner"
    )

    entry = db.query(AuditLog).filter_by(action="exchange_rate.ecb_republished").one()
    assert entry.resource == "exchange_rate:EUR/USD"
    assert entry.before["rate"] == "1.1355"
    assert entry.after["rate"] == "1.1400"
    assert entry.actor == "owner"


def test_publishing_a_then_b_then_a_again_is_three_observations_and_the_last_wins(db):
    """Por eso no hay una restricción única sobre la tasa: volver al valor
    original es una republicación legítima, no un duplicado."""
    a = rate_set(YESTERDAY)
    b = rate_set(YESTERDAY, dict(REAL_RATES, USD=Decimal("1.1400")))

    for item in (a, b, a):
        service(db, FakeFeed(daily=item)).refresh_daily(actor="owner")

    assert [row.rate for row in ecb_rows(db, "USD")] == [
        Decimal("1.1355"),
        Decimal("1.1400"),
        Decimal("1.1355"),
    ]
    chosen = EcbExchangeRateProvider(db).rate_for(base="EUR", quote="USD", on=TODAY)
    assert chosen.rate == Decimal("1.1355")


def test_a_new_day_adds_a_new_observation_and_leaves_the_old_one(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    service(db, FakeFeed(daily=rate_set(TODAY))).refresh_daily(actor="owner")

    assert [row.effective_date for row in ecb_rows(db, "USD")] == [YESTERDAY, TODAY]


# --- Todo o nada --------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        FeedUnavailableError("the ECB did not answer"),
        FeedUnavailableError("the ECB feed is not well-formed XML"),
        FeedUnavailableError("the ECB feed has no dated rates"),
    ],
)
def test_a_failed_fetch_stores_nothing_and_keeps_what_was_there(db, failure):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    before = count(db)

    with pytest.raises(FeedUnavailableError):
        service(db, FakeFeed(daily=failure)).refresh_daily(actor="owner")

    assert count(db) == before
    assert len(ecb_rows(db, "USD")) == 1
    # Un fallo no se anota como «refresco sin cambios».
    assert actions(db).count("exchange_rate.ecb_daily") == 1


def test_a_feed_with_no_admitted_currency_is_an_error_not_no_change(db):
    only_foreign = rate_set(YESTERDAY, {"JPY": Decimal("178.41"), "CHF": Decimal("0.9461")})

    with pytest.raises(FeedUnavailableError, match="no currency"):
        service(db, FakeFeed(daily=only_foreign)).refresh_daily(actor="owner")

    assert count(db) == 0


def test_a_date_in_the_future_is_rejected_and_nothing_is_stored(db):
    future = rate_set(TODAY + datetime.timedelta(days=2))

    with pytest.raises(FeedUnavailableError, match="future"):
        service(db, FakeFeed(daily=future)).refresh_daily(actor="owner")

    assert count(db) == 0


def test_a_feed_quoted_against_another_base_is_rejected(db):
    odd = rate_set(YESTERDAY)
    odd = type(odd)(**{**odd.__dict__, "base": "USD"})

    with pytest.raises(FeedUnavailableError, match="USD"):
        service(db, FakeFeed(daily=odd)).refresh_daily(actor="owner")

    assert count(db) == 0


def test_a_database_failure_midway_rolls_everything_back(db, monkeypatch):
    real_commit = db.commit

    def boom():
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(RuntimeError):
        service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    monkeypatch.setattr(db, "commit", real_commit)

    assert count(db) == 0


def test_a_denied_call_stores_nothing(db):
    with pytest.raises(ApiBudgetExceededError):
        service(db, FakeFeed(daily=ApiBudgetExceededError("no room"))).refresh_daily(actor="owner")

    assert count(db) == 0


# --- Histórico: recuperación explícita, nunca respaldo -------------------------


def test_a_failed_daily_refresh_never_falls_back_to_the_history(db):
    feed = FakeFeed(
        daily=FeedUnavailableError("the ECB did not answer"),
        history=[rate_set(YESTERDAY)],
    )

    with pytest.raises(FeedUnavailableError):
        service(db, feed).refresh_daily(actor="owner")

    assert feed.history_calls == 0
    assert count(db) == 0


def test_the_history_is_used_only_when_asked_and_fills_the_gap(db):
    days = [TODAY - datetime.timedelta(days=n) for n in (5, 4, 1)]
    feed = FakeFeed(history=[rate_set(day) for day in days])

    result = service(db, feed).backfill_history(actor="owner")

    assert feed.history_calls == 1 and feed.daily_calls == 0
    assert result.mode == "backfill"
    assert result.days_examined == 3
    assert result.stored == 3 * len(ADMITTED)
    assert [row.effective_date for row in ecb_rows(db, "USD")] == sorted(days)
    assert "eurofxref-hist-90d" in ecb_rows(db, "USD")[0].note
    assert "exchange_rate.ecb_backfill" in actions(db)


def test_a_backfill_over_days_already_stored_duplicates_nothing(db):
    days = [YESTERDAY, TODAY - datetime.timedelta(days=4)]
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    result = service(db, FakeFeed(history=[rate_set(day) for day in days])).backfill_history(
        actor="owner"
    )

    assert result.unchanged == len(ADMITTED)
    assert result.stored == len(ADMITTED)
    assert len(ecb_rows(db, "USD")) == 2


def test_a_backfill_that_finds_a_republished_value_records_it(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    corrected = rate_set(YESTERDAY, dict(REAL_RATES, GBP=Decimal("0.86000")))

    result = service(db, FakeFeed(history=[corrected])).backfill_history(actor="owner")

    assert [item.pair for item in result.republished] == ["EUR/GBP"]


# --- Configuración y derechos ---------------------------------------------------


def test_without_a_real_source_configured_nothing_is_called(db):
    feed = FakeFeed(daily=rate_set(YESTERDAY))
    mock_settings = Settings(_env_file=None)

    with pytest.raises(FxSourceNotConfiguredError):
        FxRefreshService(db, mock_settings, feed=feed).refresh_daily(actor="owner")

    assert feed.daily_calls == 0


def test_without_the_right_to_store_nothing_is_called(db, monkeypatch):
    monkeypatch.setattr("app.money.fx_refresh.permits", lambda provider, right: False)
    feed = FakeFeed(daily=rate_set(YESTERDAY))

    with pytest.raises(FxSourceNotConfiguredError, match="rights"):
        service(db, feed).refresh_daily(actor="owner")

    assert feed.daily_calls == 0


def test_without_the_rights_the_provider_reads_nothing(db, monkeypatch):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    monkeypatch.setattr("app.money.ecb.permits", lambda provider, right: False)

    assert EcbExchangeRateProvider(db).rate_for(base="EUR", quote="USD", on=TODAY) is None


# --- Lectura: pares, dirección y antigüedad ------------------------------------


def test_usd_to_eur_is_the_published_eur_usd_rate_used_backwards(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    found = EcbExchangeRateProvider(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found.pair == "EUR/USD"
    conversion = convert(Money.of("11.355", "USD"), to="EUR", rate=found, on=TODAY)
    assert conversion.direction.value == "inverted"
    assert conversion.converted_amount == Decimal("10")
    assert conversion.provenance.value == "third_party_verified"
    assert conversion.effective_date == YESTERDAY
    assert conversion.ingested_at is not None


def test_there_is_no_cross_rate_between_two_non_euro_currencies(db):
    """USD→GBP no lo publica el BCE, y calcularlo es otro milestone (ADR 0020 §7)."""
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    assert EcbExchangeRateProvider(db).rate_for(base="USD", quote="GBP", on=TODAY) is None


def test_a_currency_the_ecb_does_not_publish_has_no_rate(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    assert EcbExchangeRateProvider(db).rate_for(base="VND", quote="EUR", on=TODAY) is None


def test_a_weekend_or_holiday_uses_the_last_rate_with_its_original_date(db):
    friday = TODAY - datetime.timedelta(days=3)
    service(db, FakeFeed(daily=rate_set(friday))).refresh_daily(actor="owner")

    found = EcbExchangeRateProvider(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found.effective_date == friday
    assert found.age_in_days(TODAY) == 3
    assert found.is_acceptable_on(TODAY)


def test_the_provider_never_reads_a_rate_dated_after_the_question(db):
    service(db, FakeFeed(daily=rate_set(TODAY))).refresh_daily(actor="owner")

    assert EcbExchangeRateProvider(db).rate_for(base="EUR", quote="USD", on=YESTERDAY) is None


def test_an_eight_day_old_reference_is_read_but_cannot_convert(db):
    old = TODAY - datetime.timedelta(days=8)
    service(db, FakeFeed(daily=rate_set(old))).refresh_daily(actor="owner")

    found = EcbExchangeRateProvider(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found is not None and not found.is_acceptable_on(TODAY)
    with pytest.raises(StaleRateError):
        convert(Money.of("1", "USD"), to="EUR", rate=found, on=TODAY)


def test_the_ecb_window_is_configurable_and_never_beyond_the_manual_one(db):
    old = TODAY - datetime.timedelta(days=8)
    service(db, FakeFeed(daily=rate_set(old))).refresh_daily(actor="owner")

    wide = EcbExchangeRateProvider(db, max_age_days=10).rate_for(base="USD", quote="EUR", on=TODAY)

    assert wide.is_acceptable_on(TODAY)
    with pytest.raises(ValueError):
        Settings(_env_file=None, ecb_rate_max_age_days=31)


# --- Precedencia: manual > BCE > mock -------------------------------------------


def declare(db: Session, *, age_days: int, rate: str = "0.80", quote: str = "EUR") -> None:
    db.add(
        Row(
            base_currency="USD",
            quote_currency=quote,
            rate=Decimal(rate),
            effective_date=TODAY - datetime.timedelta(days=age_days),
            source="manual:owner",
            provenance="declared",
        )
    )
    db.commit()


def resolve(db: Session, *, simulated: bool = False):
    class Config:
        allows_simulated_providers = simulated
        exchange_rate_provider = "real"
        ecb_rate_max_age_days = 7

    from app.integrations.ports import ProviderKind

    Config.exchange_rate_provider = ProviderKind.REAL
    return exchange_rates_for(db, Config())  # type: ignore[arg-type]


def test_a_fresh_manual_rate_wins_over_the_ecb(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    declare(db, age_days=2)

    found = resolve(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found.source == "manual:owner"


def test_a_stale_manual_rate_does_not_shadow_a_fresh_ecb_reference(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    declare(db, age_days=40)

    found = resolve(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found.source == ECB_SOURCE
    assert found.provenance.value == "third_party_verified"


def test_a_twenty_day_manual_rate_still_beats_a_fresh_ecb_one(db):
    """Manual conserva su ventana de 30 días: precedencia, no frescura."""
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    declare(db, age_days=20)

    assert resolve(db).rate_for(base="USD", quote="EUR", on=TODAY).source == "manual:owner"


def test_the_manual_provider_does_not_read_ecb_rows_and_the_ecb_provider_reads_only_them(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")
    declare(db, age_days=1)

    manual = ManualExchangeRateProvider(db).rate_for(base="USD", quote="EUR", on=TODAY)
    ecb = EcbExchangeRateProvider(db).rate_for(base="USD", quote="EUR", on=TODAY)

    assert manual.source == "manual:owner"
    assert ecb.source == ECB_SOURCE


def test_with_the_default_mock_configuration_ecb_rows_are_ignored(db):
    """`EXCHANGE_RATE_PROVIDER=mock` es exactamente el sistema de antes."""
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    class Config:
        allows_simulated_providers = False
        exchange_rate_provider = "mock"
        ecb_rate_max_age_days = 7

    assert exchange_rates_for(db, Config()).rate_for(base="USD", quote="EUR", on=TODAY) is None  # type: ignore[arg-type]


def test_the_ecb_beats_the_fixture_where_fixtures_are_allowed(db):
    service(db, FakeFeed(daily=rate_set(YESTERDAY))).refresh_daily(actor="owner")

    found = resolve(db, simulated=True).rate_for(base="USD", quote="EUR", on=TODAY)

    assert found.source == ECB_SOURCE


def test_without_an_acceptable_ecb_rate_the_fixture_fills_in_only_where_allowed(db):
    old = TODAY - datetime.timedelta(days=9)
    service(db, FakeFeed(daily=rate_set(old))).refresh_daily(actor="owner")

    with_fixture = resolve(db, simulated=True).rate_for(base="USD", quote="EUR", on=TODAY)
    without = resolve(db, simulated=False).rate_for(base="USD", quote="EUR", on=TODAY)

    assert with_fixture.provenance.value == "simulated"
    assert without is not None and not without.is_acceptable_on(TODAY)  # caducada: se rechazará
