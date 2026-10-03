# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""Los agregados del registro de ingresos verificados, solo lectura (Milestone 45, ADR 0030), sobre SQLite y PostgreSQL.

Un «mundo» de importes conocidos (todo entra por la puerta de eventos, con la hora del hecho fijada) y lo que se afirma:

- el ingreso y el reembolso verificados son solo `ORDER_PAYMENT`; un duplicado o una discrepancia es dinero en
  revisión y **no** infla el ingreso; su reembolso reduce **esa** clase y no el ingreso legítimo;
- un `CONFLICT` o un `UNMATCHED` es evidencia pendiente, aparte, y no suma en ningún total;
- una moneda nunca se suma con otra; EUR es la única consolidada y las demás se declaran no agregables;
- el periodo es `occurred_at` en UTC, `from` inclusivo y `to` exclusivo; el resumen cuadra con el estado de los
  cobros y con la suma de las entradas; la paginación no duplica ni salta; y leer no escribe nada.
"""

import base64
import datetime
import json
from decimal import Decimal

import pytest
from payment_test_support import deliver, ingress, start_attempt
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    EXPIRED,
    SUCCEEDED,
    ScriptedPaymentProvider,
    confirm_refund,
    entries,
    new_order,
    refund_of,
    reload,
)
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.db.models.payment import Payment
from app.money.money import Money
from app.revenue import aggregates
from app.revenue.aggregates import Period
from app.revenue.pagination import MAX_PAGE_SIZE, EntryCursor, InvalidCursorError

UTC = datetime.UTC


def at(day: int, hour: int = 12, month: int = 10) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, 0, tzinfo=UTC)


@pytest.fixture()
def provider() -> ScriptedPaymentProvider:
    return ScriptedPaymentProvider()


def build_world(db: Session, provider: ScriptedPaymentProvider) -> dict[str, Payment]:
    """Ocho entradas, dos monedas, las tres clases, y dos eventos de dinero que no se pudieron asentar."""
    a = start_attempt(db, new_order(db, "A", "sim_a"), provider)
    deliver(db, provider, SUCCEEDED, a, occurred_at=at(1))
    confirm_refund(db, provider, refund_of(db, provider, a, "20.00"), occurred_at=at(2))

    order_b = new_order(db, "B", "sim_b")
    first = start_attempt(db, order_b, provider)
    deliver(db, provider, EXPIRED, first)
    second = start_attempt(db, order_b, provider)
    deliver(db, provider, SUCCEEDED, second, occurred_at=at(3))
    deliver(db, provider, SUCCEEDED, first, occurred_at=at(3))  # un segundo cobro real, a la misma hora
    first = reload(db, first)
    refund = refund_of(db, provider, first, "50.00", reason="duplicate_capture")
    confirm_refund(db, provider, refund, occurred_at=at(4))

    c = start_attempt(db, new_order(db, "C", "sim_c"), provider)
    deliver(db, provider, SUCCEEDED, c, amount="12.50", occurred_at=at(5))

    d = start_attempt(db, new_order(db, "D", "sim_d", price="15.00", currency="USD"), provider)
    deliver(db, provider, SUCCEEDED, d, occurred_at=datetime.datetime(2026, 10, 6, 0, 0, tzinfo=UTC))  # justo en `to`
    confirm_refund(db, provider, refund_of(db, provider, d, "5.00"), occurred_at=at(7))

    e = start_attempt(db, new_order(db, "E", "sim_e"), provider)
    deliver(db, provider, SUCCEEDED, e, currency="USD", occurred_at=at(8))  # CONFLICT: otra moneda que la del cobro
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref="simpay_stranger",
        client_reference="no-such-payment",
        amount=Money.of("5.00", "EUR"),
        occurred_at=at(9),
    )
    assert ingress(db, provider).receive(provider.name, headers, raw).outcome == "unmatched"
    return {"a": reload(db, a), "dup": first, "mismatch": reload(db, c), "usd": reload(db, d)}


def verified(result: dict, currency: str) -> dict:
    return next(row for row in result["verified"] if row["currency"] == currency)


# --- El resumen ------------------------------------------------------------------------------------------------------


def test_the_summary_of_everything_splits_verified_review_and_pending_money_by_currency(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period())

    assert result["entries"] == 8
    assert result["verified"] == [
        {
            "currency": "EUR",
            "revenue": "100.0000",
            "refunds": "20.0000",
            "net": "80.0000",
            "captures": 2,
            "refund_count": 1,
        },
        {
            "currency": "USD",
            "revenue": "30.0000",
            "refunds": "5.0000",
            "net": "25.0000",
            "captures": 1,
            "refund_count": 1,
        },
    ]
    assert result["under_review"] == [
        {
            "currency": "EUR",
            "classification": "DUPLICATE_RECEIPT",
            "received": "50.0000",
            "refunded": "50.0000",
            "outstanding": "0.0000",
            "receipts": 1,
            "refund_count": 1,
        },
        {
            "currency": "EUR",
            "classification": "MISMATCH_RECEIPT",
            "received": "12.5000",
            "refunded": "0.0000",
            "outstanding": "12.5000",
            "receipts": 1,
            "refund_count": 0,
        },
    ]
    assert result["pending_evidence"] == {
        "count": 2,
        "by_currency": [
            {"currency": "EUR", "event_type": "payment.succeeded", "count": 1, "amount": "5.0000"},
            {"currency": "USD", "event_type": "payment.succeeded", "count": 1, "amount": "50.0000"},
        ],
    }
    assert result["scope"]["is_accounting_ledger"] is False


def test_a_duplicate_or_a_mismatch_never_inflates_the_verified_revenue(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period())

    # 50 (A) + 50 (la captura canónica de B) = 100; los 50 del duplicado y los 12.50 de la discrepancia no cuentan.
    assert verified(result, "EUR")["revenue"] == "100.0000"
    assert verified(result, "EUR")["captures"] == 2


def test_refunding_a_duplicate_reduces_the_money_under_review_and_never_the_verified_revenue(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period())

    assert verified(result, "EUR")["refunds"] == "20.0000", "only the refund of the normal capture"
    duplicate = next(r for r in result["under_review"] if r["classification"] == "DUPLICATE_RECEIPT")
    assert (duplicate["received"], duplicate["refunded"], duplicate["outstanding"]) == ("50.0000", "50.0000", "0.0000")


def test_pending_evidence_is_never_part_of_any_total(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period())

    assert result["pending_evidence"]["count"] == 2
    assert verified(result, "EUR")["revenue"] == "100.0000", "the 5.00 EUR unmatched is not revenue"
    assert verified(result, "USD")["revenue"] == "30.0000", "the 50.00 USD conflict is not revenue"
    assert result["entries"] == 8, "the evidence is not a ledger entry"


def test_only_eur_is_consolidated_and_the_other_currencies_are_declared_not_aggregable(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period())

    assert result["consolidated_eur"] == {
        "currency": "EUR",
        "revenue": "100.0000",
        "refunds": "20.0000",
        "net": "80.0000",
        "under_review_outstanding": "12.5000",
    }
    assert [row["currency"] for row in result["non_aggregable_currencies"]] == ["USD"]
    assert "never added" in result["non_aggregable_currencies"][0]["reason"]


def test_without_any_eur_entry_there_is_no_consolidated_block_and_nothing_is_converted(db: Session, provider):
    d = start_attempt(db, new_order(db, "D", "sim_d", price="15.00", currency="USD"), provider)
    deliver(db, provider, SUCCEEDED, d, occurred_at=at(6))

    result = aggregates.summary(db, Period())

    assert result["consolidated_eur"] is None, "«Sin datos»: no EUR fact, and no conversion of the USD one"
    assert verified(result, "USD")["revenue"] == "30.0000"
    assert [row["currency"] for row in result["non_aggregable_currencies"]] == ["USD"]


def test_an_empty_ledger_has_no_data_and_no_invented_zeros(db: Session):
    result = aggregates.summary(db, Period())

    assert result["entries"] == 0 and result["verified"] == [] and result["under_review"] == []
    assert result["consolidated_eur"] is None and result["non_aggregable_currencies"] == []
    assert result["pending_evidence"] == {"count": 0, "by_currency": []}


# --- El periodo ------------------------------------------------------------------------------------------------------


def test_the_period_is_occurred_at_with_from_inclusive_and_to_exclusive(db: Session, provider):
    build_world(db, provider)

    # `to` = 6 de octubre a las 00:00: la captura en USD ocurrida justo en ese instante **no** entra.
    before = aggregates.summary(db, Period(start=at(3, 0), end=at(6, 0)))
    assert [r["currency"] for r in before["verified"]] == ["EUR"]
    assert verified(before, "EUR")["revenue"] == "50.0000" and verified(before, "EUR")["refunds"] == "0.0000"
    assert before["entries"] == 4 and before["pending_evidence"]["count"] == 0

    # `from` = ese mismo instante: ahora **sí** entra.
    after = aggregates.summary(db, Period(start=at(6, 0)))
    assert [r["currency"] for r in after["verified"]] == ["USD"]
    assert after["entries"] == 2 and after["consolidated_eur"] is None and after["pending_evidence"]["count"] == 2


def test_a_window_with_only_a_refund_has_a_negative_net_not_a_hidden_zero(db: Session, provider):
    build_world(db, provider)

    result = aggregates.summary(db, Period(start=at(2, 0), end=at(3, 0)))

    assert verified(result, "EUR") == {
        "currency": "EUR",
        "revenue": "0.0000",
        "refunds": "20.0000",
        "net": "-20.0000",
        "captures": 0,
        "refund_count": 1,
    }


def test_the_period_counts_when_the_fact_happened_not_when_it_arrived(db: Session, provider):
    payment = start_attempt(db, new_order(db), provider)
    deliver(db, provider, SUCCEEDED, payment, occurred_at=at(15, month=9))  # procesado hoy, ocurrido en septiembre

    september = aggregates.summary(db, Period(start=at(1, 0, 9), end=at(1, 0, 10)))
    october = aggregates.summary(db, Period(start=at(1, 0, 10), end=at(1, 0, 11)))

    assert verified(september, "EUR")["revenue"] == "50.0000" and october["entries"] == 0


def test_a_period_must_be_in_utc_and_not_empty():
    with pytest.raises(ValueError, match="time zone"):
        Period(start=datetime.datetime(2026, 10, 1))
    with pytest.raises(ValidationError, match="empty"):
        Period(start=at(5), end=at(5))
    with pytest.raises(ValidationError, match="empty"):
        Period(start=at(6), end=at(5))


# --- Cuadra con los cobros y con las entradas -------------------------------------------------------------------------


def test_the_summary_matches_what_the_payments_say_for_every_currency_and_class(db: Session, provider):
    build_world(db, provider)
    classes = {
        "SUCCEEDED": "ORDER_PAYMENT",
        "DUPLICATE_CAPTURE": "DUPLICATE_RECEIPT",
        "CAPTURE_MISMATCH": "MISMATCH_RECEIPT",
    }
    truth: dict[tuple[str, str], Decimal] = {}
    for payment in db.scalars(select(Payment)):
        if payment.status in classes:
            key = (payment.currency, classes[payment.status])
            money = Decimal(str(payment.captured_amount)) - Decimal(str(payment.refunded_amount))
            truth[key] = truth.get(key, Decimal(0)) + money

    result = aggregates.summary(db, Period())

    reported = {(r["currency"], "ORDER_PAYMENT"): Decimal(r["net"]) for r in result["verified"]}
    reported |= {(r["currency"], r["classification"]): Decimal(r["outstanding"]) for r in result["under_review"]}
    assert reported == truth


def test_the_summary_is_the_sum_of_the_entries_that_explain_it(db: Session, provider):
    build_world(db, provider)
    page = aggregates.entries_page(db, period=Period(), limit=MAX_PAGE_SIZE)
    sums: dict[tuple[str, str, str], Decimal] = {}
    for entry in page.entries:
        key = (entry.currency, entry.classification, entry.kind)
        sums[key] = sums.get(key, Decimal(0)) + Decimal(str(entry.amount))

    result = aggregates.summary(db, Period())

    assert not page.has_more
    for row in result["verified"]:
        assert Decimal(row["revenue"]) == sums.get((row["currency"], "ORDER_PAYMENT", "CAPTURE"), Decimal(0))
        assert Decimal(row["refunds"]) == sums.get((row["currency"], "ORDER_PAYMENT", "REFUND"), Decimal(0))
    for row in result["under_review"]:
        assert Decimal(row["received"]) == sums.get((row["currency"], row["classification"], "CAPTURE"), Decimal(0))
        assert Decimal(row["refunded"]) == sums.get((row["currency"], row["classification"], "REFUND"), Decimal(0))


def test_sums_are_exact_decimals_never_binary_floats(db: Session, provider):
    for number, price in enumerate(("0.05", "0.10", "0.15")):  # 0.10 + 0.20 + 0.30
        payment = start_attempt(db, new_order(db, f"W{number}", f"sim_w{number}", price=price), provider)
        deliver(db, provider, SUCCEEDED, payment, occurred_at=at(1 + number))

    result = aggregates.summary(db, Period())

    assert verified(result, "EUR")["revenue"] == "0.6000", (
        "0.1 + 0.2 + 0.3 is 0.6 with Decimal, 0.6000000000000001 with float"
    )


def test_a_very_large_amount_is_summed_exactly_on_postgresql(db: Session, provider):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("SQLite sums in binary floating point: exactness at 17 digits is a PostgreSQL guarantee")
    for number in range(2):
        payment = start_attempt(db, new_order(db, f"L{number}", f"sim_l{number}", price="12345678901234.56"), provider)
        deliver(db, provider, SUCCEEDED, payment, occurred_at=at(1 + number))

    result = aggregates.summary(db, Period())

    assert verified(result, "EUR")["revenue"] == "49382715604938.2400"


# --- La serie --------------------------------------------------------------------------------------------------------


def test_the_daily_series_has_only_buckets_with_entries_and_splits_review_money(db: Session, provider):
    build_world(db, provider)

    result = aggregates.series(db, granularity="day", period=Period(start=at(1, 0), end=at(10, 0)))

    buckets = {(b["bucket"], b["currency"]): b for b in result["buckets"]}
    assert sorted(buckets) == [
        ("2026-10-01", "EUR"), ("2026-10-02", "EUR"), ("2026-10-03", "EUR"), ("2026-10-04", "EUR"),
        ("2026-10-05", "EUR"), ("2026-10-06", "USD"), ("2026-10-07", "USD"),
    ]  # fmt: skip
    assert "2026-10-08" not in {b for b, _ in buckets}, "no entries that day: no bucket, no invented zero"
    third = buckets[("2026-10-03", "EUR")]
    assert (third["revenue"], third["under_review_received"], third["entries"]) == ("50.0000", "50.0000", 2)
    second = buckets[("2026-10-02", "EUR")]
    assert (second["revenue"], second["refunds"], second["net"]) == ("0.0000", "20.0000", "-20.0000")
    fourth = buckets[("2026-10-04", "EUR")]
    assert (fourth["under_review_refunded"], fourth["revenue"], fourth["refunds"]) == ("50.0000", "0.0000", "0.0000")


def test_the_monthly_series_adds_up_to_the_summary_and_keeps_currencies_apart(db: Session, provider):
    build_world(db, provider)

    result = aggregates.series(db, granularity="month", period=Period(start=at(1, 0), end=at(1, 0, 11)))
    summary = aggregates.summary(db, Period(start=at(1, 0), end=at(1, 0, 11)))

    by_currency = {b["currency"]: b for b in result["buckets"]}
    assert set(by_currency) == {"EUR", "USD"} and {b["bucket"] for b in result["buckets"]} == {"2026-10"}
    assert by_currency["EUR"]["revenue"] == verified(summary, "EUR")["revenue"] == "100.0000"
    assert by_currency["EUR"]["under_review_received"] == "62.5000"
    assert by_currency["USD"]["net"] == verified(summary, "USD")["net"] == "25.0000"


def test_a_month_boundary_in_utc_separates_the_buckets(db: Session, provider):
    last = start_attempt(db, new_order(db, "S", "sim_s"), provider)
    deliver(db, provider, SUCCEEDED, last, occurred_at=datetime.datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC))
    first = start_attempt(db, new_order(db, "O", "sim_o"), provider)
    deliver(db, provider, SUCCEEDED, first, occurred_at=datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC))

    months = aggregates.series(db, granularity="month", period=Period(start=at(1, 0, 9), end=at(1, 0, 11)))
    days = aggregates.series(db, granularity="day", period=Period(start=at(29, 0, 9), end=at(3, 0, 10)))

    assert [b["bucket"] for b in months["buckets"]] == ["2026-09", "2026-10"]
    assert [b["bucket"] for b in days["buckets"]] == ["2026-09-30", "2026-10-01"]


def test_the_series_window_is_bounded_and_the_granularity_is_closed():
    now = at(10)
    with pytest.raises(ValidationError, match="at most 366 days"):
        aggregates.resolve_series_period("day", Period(start=now - datetime.timedelta(days=400), end=now), now=now)
    with pytest.raises(ValidationError, match="at most 1096 days"):
        aggregates.resolve_series_period("month", Period(start=now - datetime.timedelta(days=1200), end=now), now=now)
    with pytest.raises(ValidationError, match="granularity"):
        aggregates.resolve_series_period("hour", Period(), now=now)

    day = aggregates.resolve_series_period("day", Period(), now=now)
    month = aggregates.resolve_series_period("month", Period(), now=now)
    assert (day.end, now - day.start) == (now, datetime.timedelta(days=30))
    assert (month.end, now - month.start) == (now, datetime.timedelta(days=365))


# --- La lista de entradas ---------------------------------------------------------------------------------------------


def walk(db: Session, limit: int, **filters) -> list[list]:
    pages, cursor = [], None
    while True:
        page = aggregates.entries_page(db, period=Period(), cursor=cursor, limit=limit, **filters)
        pages.append(page.entries)
        if not page.has_more:
            assert page.next_cursor is None
            return pages
        assert page.next_cursor is not None
        cursor = page.next_cursor


def stamp(entry) -> datetime.datetime:
    return entry.occurred_at if entry.occurred_at.tzinfo else entry.occurred_at.replace(tzinfo=UTC)


def test_pagination_walks_every_entry_once_newest_first_with_a_total_order(db: Session, provider):
    build_world(db, provider)
    everything = {e.id for e in entries(db)}

    pages = walk(db, 3)

    flat = [entry for page in pages for entry in page]
    assert [len(p) for p in pages] == [3, 3, 2]
    assert {e.id for e in flat} == everything and len(flat) == len(everything), "none missing, none repeated"
    keys = [(stamp(e), e.id) for e in flat]
    assert keys == sorted(keys, reverse=True), "occurred_at DESC, id DESC: total and deterministic"
    assert len({stamp(e) for e in flat}) < len(flat), "two entries share a timestamp: the id breaks the tie"


def test_a_last_page_that_is_exactly_full_says_there_is_nothing_more(db: Session, provider):
    build_world(db, provider)  # 8 entradas

    pages = walk(db, 4)  # dos páginas llenas: la segunda llega justo al límite
    whole = aggregates.entries_page(db, period=Period(), limit=8)  # una sola página, exactamente llena
    short = aggregates.entries_page(db, period=Period(), limit=9)

    assert [len(page) for page in pages] == [4, 4], "no empty third page"
    assert (len(whole.entries), whole.has_more, whole.next_cursor) == (8, False, None)
    assert (len(short.entries), short.has_more, short.next_cursor) == (8, False, None)
    assert aggregates.entries_page(db, period=Period(), limit=7).has_more is True


def test_a_new_entry_while_walking_does_not_repeat_or_skip_anything(db: Session, provider):
    build_world(db, provider)
    first = aggregates.entries_page(db, period=Period(), limit=3)
    assert first.next_cursor is not None
    seen = [e.id for e in first.entries]

    late = start_attempt(db, new_order(db, "N", "sim_n"), provider)
    deliver(db, provider, SUCCEEDED, late, occurred_at=at(20))  # más reciente que todo lo visto: entra por arriba
    cursor, rest = first.next_cursor, []
    while cursor:
        page = aggregates.entries_page(db, period=Period(), cursor=cursor, limit=3)
        rest += [e.id for e in page.entries]
        cursor = page.next_cursor

    assert len(seen + rest) == len(set(seen + rest)) == 8, "the new entry is outside the walk in progress"


def test_the_page_filters_by_currency_class_kind_and_period_and_composes_with_the_cursor(db: Session, provider):
    build_world(db, provider)

    usd = [e for page in walk(db, 1, currency="USD") for e in page]
    review = [e for page in walk(db, 1, classification="DUPLICATE_RECEIPT") for e in page]
    refunds = [e for page in walk(db, 2, kind="REFUND") for e in page]
    window = aggregates.entries_page(db, period=Period(start=at(3, 0), end=at(6, 0)), limit=MAX_PAGE_SIZE)

    assert {e.currency for e in usd} == {"USD"} and len(usd) == 2
    assert {e.classification for e in review} == {"DUPLICATE_RECEIPT"} and len(review) == 2
    assert {e.kind for e in refunds} == {"REFUND"} and len(refunds) == 3
    assert len(window.entries) == 4 and all(at(3, 0) <= stamp(e) < at(6, 0) for e in window.entries)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "!!!",
        "a" * 300,
        "bm90LWpzb24",  # base64url de «not-json»
        base64.urlsafe_b64encode(json.dumps({"v": 2, "t": "2026-10-01T00:00:00+00:00", "i": "x"}).encode()).decode(),
        base64.urlsafe_b64encode(json.dumps({"v": 1, "t": "2026-10-01T00:00:00", "i": "x"}).encode()).decode(),
        base64.urlsafe_b64encode(
            json.dumps({"v": 1, "t": "2026-10-01T00:00:00+00:00", "i": "a b; DROP"}).encode()
        ).decode(),
        base64.urlsafe_b64encode(json.dumps({"v": 1, "t": "yesterday", "i": "x"}).encode()).decode(),
    ],
)
def test_a_cursor_that_this_service_did_not_issue_is_a_validation_error_never_a_page(db: Session, bad):
    with pytest.raises(InvalidCursorError):
        aggregates.entries_page(db, period=Period(), cursor=bad)


def test_the_cursor_round_trips_and_carries_nothing_but_a_position():
    cursor = EntryCursor(occurred_at=at(3), entry_id="abc-123")

    decoded = EntryCursor.decode(cursor.encode())

    assert decoded == cursor
    assert json.loads(base64.urlsafe_b64decode(cursor.encode() + "==")) == {
        "i": "abc-123", "t": "2026-10-03T12:00:00+00:00", "v": 1,
    }  # fmt: skip


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_SIZE + 1])
def test_the_page_size_is_bounded(db: Session, limit):
    with pytest.raises(ValidationError, match="limit"):
        aggregates.entries_page(db, period=Period(), limit=limit)


def test_the_filters_are_closed_vocabularies(db: Session):
    with pytest.raises(ValidationError, match="classification"):
        aggregates.entries_page(db, period=Period(), classification="REVENUE")
    with pytest.raises(ValidationError, match="kind"):
        aggregates.entries_page(db, period=Period(), kind="REVERSAL")


# --- Solo lectura -----------------------------------------------------------------------------------------------------


def test_reading_the_aggregates_never_writes(db: Session, provider, engine):
    build_world(db, provider)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    aggregates.summary(db, Period())
    aggregates.series(db, granularity="day", period=Period(start=at(1, 0), end=at(10, 0)))
    aggregates.series(db, granularity="month", period=Period(start=at(1, 0), end=at(1, 0, 11)))
    walk(db, 2)

    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT"))]
    assert statements and writes == [], writes
    assert len(entries(db)) == 8
