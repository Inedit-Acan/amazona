# ruff: noqa: F811 - los fixtures de pytest se importan del módulo de apoyo y los tests los piden por su nombre
"""La procedencia del dinero llega a la API sin deducirse y sin mezclarse (Milestone 46, Commit 3, ADR 0031 §10 y §22).

Las lecturas de ingresos devuelven cada cifra **por origen** (`provider_kind`: `mock`, `sandbox`, `real`), tal como está
guardado en la entrada o en el evento. Lo que se afirma, sobre SQLite y PostgreSQL:

- cada origen, solo y en cualquier combinación, sale con **sus** cifras: ninguna fila ni ninguna cifra es la suma de
  orígenes distintos (los importes de cada origen son distintos para que una suma se note);
- una moneda tampoco se suma con otra dentro de un origen, y un origen sin datos no aparece (ni como cero);
- la evidencia pendiente (`UNMATCHED`, `CONFLICT`) y el dinero en revisión se separan por el origen del hecho;
- `?provider_kind=` acota a un origen, es un vocabulario cerrado (otro valor es un 422) y compone con el cursor;
- el cobro y el reembolso de un pedido llevan su origen, y el pedido **no** inventa uno: `is_simulated` es contexto;
- nada de esto depende de `Order.is_simulated`, de `ProviderBinding.is_simulated` ni de la configuración de ahora;
- el contrato antiguo que sumaba orígenes (`consolidated_eur`) ya no existe.
"""

import itertools
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from payment_test_support import (
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    deliver,
    events,
    ingress,
    start_attempt,
)
from reconciliation_test_support import db, engine, factory  # noqa: F401 - fixtures de pytest
from revenue_test_support import (
    EXPIRED,
    SUCCEEDED,
    capture,
    confirm_refund,
    duplicate_pair,
    entries,
    mismatched_capture,
    new_order,
    refund_of,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ValidationError
from app.db.models.order import Order
from app.db.models.payment import Payment
from app.db.session import get_db
from app.integrations.registry import ProviderBinding, ProviderRegistry
from app.main import app
from app.money.money import Money
from app.reconciliation.report import build_status
from app.revenue import aggregates
from app.revenue.aggregates import Period
from app.revenue.evidence import money

SETTINGS = Settings(_env_file=None)
ORIGINS = {"mock": MockPaymentProvider, "sandbox": SandboxPaymentProvider, "real": RealPaymentProvider}
#: Un precio distinto por origen (la captura es 2 × precio): una suma de orígenes no se parece a ninguna cifra.
PRICES = {"mock": "10.00", "sandbox": "20.00", "real": "40.00"}
CAPTURED = {"mock": Decimal("20"), "sandbox": Decimal("40"), "real": Decimal("80")}
REFUNDED = Decimal("5")
COMBINATIONS = [combo for size in (1, 2, 3) for combo in itertools.combinations(ORIGINS, size)]


def combo_id(combo: tuple[str, ...]) -> str:
    return "+".join(combo)


@pytest.fixture()
def client(db: Session, factory):
    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)


def origin_world(db: Session, origins, *, currency: str = "EUR", tag: str = "") -> dict[str, Payment]:
    """Por cada origen, una captura (2 × su precio) y un reembolso de 5.00, todo por la puerta de eventos."""
    payments = {}
    for origin in origins:
        provider = ORIGINS[origin]()
        order = new_order(
            db, f"W {origin} {currency}{tag}", f"sim_{origin}_{currency}{tag}", price=PRICES[origin], currency=currency
        )
        payments[origin] = capture(db, provider, order)
        confirm_refund(db, provider, refund_of(db, provider, payments[origin], "5.00"))
    return payments


def verified_by_origin(result: dict, currency: str = "EUR") -> dict[str, dict]:
    return {row["provider_kind"]: row for row in result["verified"] if row["currency"] == currency}


# --- 1 · Cada origen solo, y en cualquier combinación ------


@pytest.mark.parametrize("combo", COMBINATIONS, ids=combo_id)
def test_every_combination_of_origins_keeps_each_origin_apart_and_adds_none_to_another(db: Session, combo):
    origin_world(db, combo)

    result = aggregates.summary(db, Period())

    rows = verified_by_origin(result)
    assert set(rows) == set(combo), "an origin without data does not appear, and one with data always does"
    for origin in combo:
        assert (rows[origin]["revenue"], rows[origin]["refunds"]) == (money(CAPTURED[origin]), money(REFUNDED))
        assert rows[origin]["net"] == money(CAPTURED[origin] - REFUNDED)
    assert [row["provider_kind"] for row in result["verified"]] == sorted(combo), "a stable order, not by amount"
    assert result["entries_by_provider_kind"] == [{"provider_kind": o, "entries": 2} for o in sorted(combo)]
    assert result["entries"] == 2 * len(combo) == sum(r["entries"] for r in result["entries_by_provider_kind"])
    assert sorted(row["provider_kind"] for row in result["consolidated_eur_by_origin"]) == sorted(combo)
    if len(combo) > 1:
        everything = json.dumps(result)
        assert money(sum(CAPTURED[o] for o in combo)) not in everything, "no figure is the sum of two origins"
        assert money(sum(CAPTURED[o] - REFUNDED for o in combo)) not in everything


def test_the_three_origins_together_have_no_total_that_crosses_them(db: Session):
    origin_world(db, ORIGINS)

    result = aggregates.summary(db, Period())

    moneyish = {
        "revenue",
        "refunds",
        "net",
        "received",
        "refunded",
        "outstanding",
        "amount",
        "under_review_outstanding",
    }
    for block in ("verified", "under_review", "consolidated_eur_by_origin"):
        assert all("provider_kind" in row for row in result[block]), f"{block} has a row with no origin"
    assert moneyish.isdisjoint(result), "no money figure sits at the top level, where an origin could be missing"
    assert "consolidated_eur" not in result
    assert "cross_origin_totals" in result["scope"]["excludes"]
    assert "never added across origins" in result["scope"]["basis"]


@pytest.mark.parametrize("origin", ORIGINS)
def test_the_filter_narrows_to_one_origin_and_equals_that_origins_rows_of_the_full_answer(db: Session, origin: str):
    origin_world(db, ORIGINS)
    full = aggregates.summary(db, Period())

    only = aggregates.summary(db, Period(), provider_kind=origin)

    assert [r["provider_kind"] for r in only["verified"]] == [origin]
    assert only["verified"] == [r for r in full["verified"] if r["provider_kind"] == origin]
    assert only["consolidated_eur_by_origin"] == [
        r for r in full["consolidated_eur_by_origin"] if r["provider_kind"] == origin
    ]
    assert only["entries"] == 2 and only["entries_by_provider_kind"] == [{"provider_kind": origin, "entries": 2}]


def test_asking_for_an_origin_without_data_answers_no_data_not_zeros(db: Session):
    origin_world(db, ("mock",))

    result = aggregates.summary(db, Period(), provider_kind="real")

    assert result["entries"] == 0 and result["entries_by_provider_kind"] == []
    assert result["verified"] == [] and result["under_review"] == [] and result["consolidated_eur_by_origin"] == []
    assert result["pending_evidence"] == {"count": 0, "by_currency": []}


def test_an_empty_ledger_lists_no_origin_at_all(db: Session):
    result = aggregates.summary(db, Period())

    assert result["entries_by_provider_kind"] == [] and result["verified"] == []
    assert result["consolidated_eur_by_origin"] == [] and result["pending_evidence"]["by_currency"] == []


@pytest.mark.parametrize("bad", ["composite", "REAL", "Mock", "", " mock", "all", "mock,sandbox", "simulated-payments"])
def test_the_filter_is_a_closed_vocabulary_and_anything_else_is_a_validation_error(db: Session, bad: str):
    period = aggregates.resolve_series_period("day", Period(), now=aggregates_now())
    with pytest.raises(ValidationError, match="provider_kind"):
        aggregates.summary(db, Period(), provider_kind=bad)
    with pytest.raises(ValidationError, match="provider_kind"):
        aggregates.series(db, granularity="day", period=period, provider_kind=bad)
    with pytest.raises(ValidationError, match="provider_kind"):
        aggregates.entries_page(db, period=Period(), provider_kind=bad)


def aggregates_now():
    import datetime

    return datetime.datetime(2026, 10, 12, tzinfo=datetime.UTC)


@pytest.mark.parametrize("path", ["summary", "series", "entries"])
@pytest.mark.parametrize("bad", ["composite", "REAL", "", "all", "mock,real"])
def test_over_http_a_bad_origin_is_a_422_never_a_mixed_answer(client: TestClient, path: str, bad: str):
    response = client.get(f"/api/revenue/{path}", params={"provider_kind": bad})

    assert response.status_code == 422, response.text
    assert "provider_kind" in response.text


# --- 2 · Monedas dentro de cada origen ------


def test_currencies_stay_apart_inside_each_origin_and_only_the_origins_with_eur_get_a_consolidated_row(db: Session):
    origin_world(db, ("mock", "sandbox"), currency="EUR")
    origin_world(db, ("mock", "real"), currency="USD", tag="_usd")

    result = aggregates.summary(db, Period())

    assert {(r["provider_kind"], r["currency"]) for r in result["verified"]} == {
        ("mock", "EUR"),
        ("mock", "USD"),
        ("sandbox", "EUR"),
        ("real", "USD"),
    }
    assert [r["provider_kind"] for r in result["consolidated_eur_by_origin"]] == ["mock", "sandbox"]
    assert all(r["currency"] == "EUR" for r in result["consolidated_eur_by_origin"])
    assert [r["currency"] for r in result["non_aggregable_currencies"]] == ["USD"]
    mock_eur = next(r for r in result["consolidated_eur_by_origin"] if r["provider_kind"] == "mock")
    assert mock_eur["revenue"] == money(CAPTURED["mock"]), "the USD of the same origin is not in its EUR"


# --- 3 · La misma referencia en orígenes distintos ------


def test_the_same_reference_in_two_origins_is_two_facts_each_in_its_own_row(db: Session):
    providers = {o: ORIGINS[o]() for o in ("mock", "sandbox")}
    for origin, provider in providers.items():
        payment = start_attempt(db, new_order(db, f"W {origin}", f"sim_{origin}"), provider)
        payment.provider_payment_ref = "pay_same"
        db.commit()
        headers, raw = provider.simulate_event(
            SUCCEEDED,
            provider_payment_ref="pay_same",
            client_reference=None,
            amount=Money.of("50.00", "EUR"),
            event_id="evt_same",
        )
        assert ingress(db, provider).receive(provider.name, headers, raw).outcome == "applied"

    result = aggregates.summary(db, Period())

    assert {o: r["revenue"] for o, r in verified_by_origin(result).items()} == {"mock": "50.0000", "sandbox": "50.0000"}
    assert "100.0000" not in json.dumps(result), "two identical references are not one fact, and are not added"
    assert result["entries_by_provider_kind"] == [
        {"provider_kind": "mock", "entries": 1},
        {"provider_kind": "sandbox", "entries": 1},
    ]


# --- 4 · Evidencia pendiente: UNMATCHED y CONFLICT por origen ------------------------------------------------------


def pending_world(db: Session) -> None:
    """Por origen, un `UNMATCHED` de importe propio y un `CONFLICT`; y un cobro normal de cada uno."""
    unmatched = {"mock": "3.00", "sandbox": "7.00", "real": "11.00"}
    for origin, provider_class in ORIGINS.items():
        provider = provider_class()
        payment = capture(db, provider, new_order(db, f"P {origin}", f"sim_p_{origin}", price=PRICES[origin]))
        deliver(db, provider, SUCCEEDED, payment, event_id=f"evt_conflict_{origin}", amount="49.00")  # CONFLICT
        headers, raw = provider.simulate_event(
            SUCCEEDED,
            provider_payment_ref=f"pay_nobody_{origin}",
            client_reference=None,
            amount=Money.of(unmatched[origin], "EUR"),
            event_id=f"evt_unmatched_{origin}",
        )
        assert ingress(db, provider).receive(provider.name, headers, raw).outcome == "unmatched"


def test_pending_evidence_is_separated_by_the_origin_stored_in_each_event_and_never_added(db: Session):
    pending_world(db)

    result = aggregates.summary(db, Period())

    rows = {r["provider_kind"]: r for r in result["pending_evidence"]["by_currency"]}
    assert set(rows) == set(ORIGINS) and result["pending_evidence"]["count"] == 6
    assert all(r["count"] == 2 for r in rows.values())
    assert {o: r["amount"] for o, r in rows.items()} == {"mock": "52.0000", "sandbox": "56.0000", "real": "60.0000"}
    assert "168.0000" not in json.dumps(result), "52 + 56 + 60 is nobody's figure"
    assert {o: r["revenue"] for o, r in verified_by_origin(result).items()} == {
        o: money(CAPTURED[o]) for o in ORIGINS
    }, "the evidence is not revenue"


@pytest.mark.parametrize("origin", ORIGINS)
def test_pending_evidence_follows_the_origin_filter(db: Session, origin: str):
    pending_world(db)

    result = aggregates.summary(db, Period(), provider_kind=origin)

    assert [r["provider_kind"] for r in result["pending_evidence"]["by_currency"]] == [origin]
    assert result["pending_evidence"]["count"] == 2


def test_the_status_of_the_reconciliation_names_the_origin_of_every_pending_event(db: Session):
    pending_world(db)

    revenue = build_status(db, SETTINGS)["revenue"]["pending_evidence"]

    assert {item["provider_kind"] for item in revenue["items"]} == set(ORIGINS)
    assert {row["provider_kind"] for row in revenue["by_currency"]} == set(ORIGINS)
    by_item = {(i["provider_kind"], i["status"]): i for i in revenue["items"]}
    assert set(by_item) == {(o, s) for o in ORIGINS for s in ("CONFLICT", "UNMATCHED")}
    stored = {e.id: e.provider_kind for e in events(db)}
    assert all(stored[item["id"]] == item["provider_kind"] for item in revenue["items"]), "as persisted, not inferred"


def test_over_http_the_pending_evidence_of_the_status_carries_the_origin(db: Session, client: TestClient):
    pending_world(db)

    body = client.get("/api/reconciliation/status").json()["revenue"]["pending_evidence"]

    assert {row["provider_kind"] for row in body["by_currency"]} == set(ORIGINS)
    assert all("provider_kind" in item for item in body["items"])


def test_an_event_stuck_in_the_retry_cycle_is_listed_with_its_stored_origin(db: Session, monkeypatch):
    from app.payments.service import PaymentService

    provider = SandboxPaymentProvider()
    payment = start_attempt(db, new_order(db), provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
    )

    def died(self, event_id):
        raise KeyboardInterrupt("the process died between storing the event and applying it")

    with monkeypatch.context() as patch:
        patch.setattr(PaymentService, "apply", died)
        with pytest.raises(KeyboardInterrupt):
            ingress(db, provider).receive(provider.name, headers, raw)
    db.rollback()
    (stored,) = events(db)
    db.execute(
        update(type(stored))
        .where(type(stored).id == stored.id)
        .values(reconcile_attempts=SETTINGS.reconcile_event_max_attempts)
    )
    db.commit()

    capped = build_status(db, SETTINGS)["events"]["capped"]

    assert capped["count"] == 1 and capped["items"][0]["provider_kind"] == "sandbox"


# --- 5 · Dinero en revisión y duplicados por origen ------


def test_money_under_review_is_separated_by_origin_and_never_inflates_a_verified_figure(db: Session):
    capture(db, MockPaymentProvider(), new_order(db, "M", "sim_m", price=PRICES["mock"]))
    duplicate_pair(db, SandboxPaymentProvider(), new_order(db, "S", "sim_s", price=PRICES["sandbox"]))
    mismatched_capture(db, RealPaymentProvider(), new_order(db, "R", "sim_r"), "12.50")

    result = aggregates.summary(db, Period())

    review = {(r["provider_kind"], r["classification"]): r for r in result["under_review"]}
    assert set(review) == {("sandbox", "DUPLICATE_RECEIPT"), ("real", "MISMATCH_RECEIPT")}
    assert review[("sandbox", "DUPLICATE_RECEIPT")]["received"] == money(CAPTURED["sandbox"])
    assert review[("real", "MISMATCH_RECEIPT")]["received"] == "12.5000"
    verified = verified_by_origin(result)
    assert verified["mock"]["revenue"] == money(CAPTURED["mock"])
    assert verified["sandbox"]["revenue"] == money(CAPTURED["sandbox"]), "only the canonical capture"
    assert "real" not in verified, "a mismatch is not verified revenue, and a real without any is not a zero"
    consolidated = {r["provider_kind"]: r for r in result["consolidated_eur_by_origin"]}
    assert consolidated["real"]["revenue"] == "0.0000" and consolidated["real"]["under_review_outstanding"] == "12.5000"


# --- 6 · Series ------


def test_the_series_has_one_bucket_per_day_origin_and_currency_and_matches_the_summary_per_origin(db: Session):
    origin_world(db, ORIGINS)
    import datetime

    window = Period(
        start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC), end=datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC)
    )

    buckets = aggregates.series(db, granularity="month", period=window)["buckets"]
    result = aggregates.summary(db, Period())

    assert all("provider_kind" in b for b in buckets)
    for origin, row in verified_by_origin(result).items():
        mine = [b for b in buckets if b["provider_kind"] == origin and b["currency"] == "EUR"]
        assert sum(Decimal(b["revenue"]) for b in mine) == Decimal(row["revenue"]), origin
        assert sum(Decimal(b["refunds"]) for b in mine) == Decimal(row["refunds"]), origin
    assert len({(b["bucket"], b["provider_kind"], b["currency"]) for b in buckets}) == len(buckets), "no bucket repeats"
    only = aggregates.series(db, granularity="month", period=window, provider_kind="sandbox")["buckets"]
    assert {b["provider_kind"] for b in only} == {"sandbox"}


# --- 7 · Entradas y paginación ------


def test_every_entry_carries_the_origin_of_its_payment_and_the_filter_composes_with_the_cursor(db: Session):
    payments = origin_world(db, ORIGINS)
    origin_world(db, ORIGINS, tag="_second")

    for origin in ORIGINS:
        seen: list = []
        cursor = None
        while True:
            page = aggregates.entries_page(db, period=Period(), cursor=cursor, limit=1, provider_kind=origin)
            seen += page.entries
            if not page.has_more:
                break
            cursor = page.next_cursor
        assert len(seen) == 4 and len({e.id for e in seen}) == 4, "every entry of the origin, once"
        assert {e.provider_kind for e in seen} == {origin}
        assert all(db.get(Payment, e.payment_id).provider_kind == origin for e in seen)
    refunds_of_one = aggregates.entries_page(db, period=Period(), provider_kind="real", kind="REFUND", currency="EUR")
    assert [e.provider_kind for e in refunds_of_one.entries] == ["real", "real"]
    assert payments["real"].provider_kind == "real"


def test_over_http_the_entries_expose_the_origin_and_the_filter_returns_only_it(db: Session, client: TestClient):
    origin_world(db, ORIGINS)

    everything = client.get("/api/revenue/entries?limit=100").json()["items"]
    only = client.get("/api/revenue/entries?limit=100&provider_kind=sandbox").json()["items"]

    assert {e["provider_kind"] for e in everything} == set(ORIGINS) and len(everything) == 6
    assert {e["provider_kind"] for e in only} == {"sandbox"} and len(only) == 2
    stored = {e.id: e.provider_kind for e in entries(db)}
    assert all(stored[e["id"]] == e["provider_kind"] for e in everything)


def test_over_http_the_summary_and_the_series_are_by_origin_and_accept_the_filter(db: Session, client: TestClient):
    origin_world(db, ORIGINS)

    summary = client.get("/api/revenue/summary").json()
    filtered = client.get("/api/revenue/summary?provider_kind=real").json()
    series = client.get("/api/revenue/series?granularity=month&from=2026-01-01T00:00:00Z&to=2027-01-01T00:00:00Z")

    assert [r["provider_kind"] for r in summary["verified"]] == sorted(ORIGINS)
    assert [r["provider_kind"] for r in filtered["verified"]] == ["real"]
    assert filtered["entries_by_provider_kind"] == [{"provider_kind": "real", "entries": 2}]
    assert series.status_code == 200 and {b["provider_kind"] for b in series.json()["buckets"]} == set(ORIGINS)


# --- 8 · Lo guardado manda: ni el pedido, ni el binding, ni la configuración ----------------------------------------


def poison(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("the origin was inferred from a simulation signal instead of what is stored")

    monkeypatch.setattr(ProviderBinding, "is_simulated", property(forbidden))
    for method in ("kind_for", "binding_for", "bindings"):
        monkeypatch.setattr(ProviderRegistry, method, forbidden)


def test_the_reads_use_only_what_is_stored_not_the_order_the_binding_or_the_configuration(
    db: Session, client: TestClient, monkeypatch
):
    origin_world(db, ORIGINS)
    baseline = client.get("/api/revenue/summary").json()
    db.execute(update(Order).values(is_simulated=False, customer_ref="cust_flipped"))  # el pedido dice lo contrario
    db.commit()
    poison(monkeypatch)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, payments_provider="real")

    try:
        again = client.get("/api/revenue/summary").json()
        entries_page = client.get("/api/revenue/entries?limit=100").json()
        series = client.get("/api/revenue/series?granularity=month&from=2026-01-01T00:00:00Z&to=2027-01-01T00:00:00Z")
    finally:
        app.dependency_overrides[get_settings] = lambda: SETTINGS

    assert again == baseline, "flipping Order.is_simulated and the provider setting changed nothing already stored"
    assert {e["provider_kind"] for e in entries_page["items"]} == set(ORIGINS) and series.status_code == 200


def test_facts_persisted_under_an_old_configuration_keep_their_origin_after_the_provider_changes(db: Session):
    old = capture(db, MockPaymentProvider(), new_order(db, "Old", "sim_old"))
    new = capture(db, SandboxPaymentProvider(), new_order(db, "New", "sim_new"))  # "el proveedor configurado cambió"

    result = aggregates.summary(db, Period())

    assert (old.provider_kind, new.provider_kind) == ("mock", "sandbox")
    assert sorted(r["provider_kind"] for r in result["verified"]) == ["mock", "sandbox"]
    assert {e.provider_kind for e in entries(db) if e.payment_id == old.id} == {"mock"}


# --- 9 · Pedidos, cobros y reembolsos ------


def test_the_order_exposes_the_origin_of_each_payment_and_refund_and_invents_none_for_itself(
    db: Session, client: TestClient
):
    orders = {}
    for origin, provider_class in ORIGINS.items():
        provider = provider_class()
        order = new_order(db, f"O {origin}", f"sim_o_{origin}", price=PRICES[origin])
        payment = capture(db, provider, order)
        confirm_refund(db, provider, refund_of(db, provider, payment, "5.00"))
        orders[origin] = order.id

    for origin, order_id in orders.items():
        body = client.get(f"/api/orders/{order_id}").json()
        assert "provider_kind" not in body, "an order has no single origin of its own"
        assert [p["provider_kind"] for p in body["payments"]] == [origin]
        assert [r["provider_kind"] for r in body["refunds"]] == [origin], "a refund's origin is its payment's"
        assert body["refunds"][0]["origin"] in {"OPERATOR", "PROVIDER"}, "`origin` is who started it, not the money"
        assert body["is_simulated"] is True, "kept for compatibility, as the context the order was created in"


def test_an_order_can_hold_payments_of_two_origins_and_each_says_its_own(db: Session, client: TestClient):
    expiring = MockPaymentProvider()
    first = start_attempt(db, new_order(db, "Two", "sim_two"), expiring)
    deliver(db, expiring, EXPIRED, first)  # el primer intento caduca; el segundo lo abre otro proveedor
    second = start_attempt(db, db.get(Order, first.order_id), SandboxPaymentProvider())

    body = client.get(f"/api/orders/{first.order_id}").json()

    assert [(p["attempt_number"], p["provider_kind"]) for p in body["payments"]] == [(1, "mock"), (2, "sandbox")]
    assert second.provider_kind == "sandbox" and "provider_kind" not in body


def test_flipping_the_order_context_does_not_change_the_origin_shown_for_its_payments(db: Session, client: TestClient):
    provider = RealPaymentProvider()
    order = new_order(db, "Flip", "sim_flip")
    capture(db, provider, order)
    before = client.get(f"/api/orders/{order.id}").json()
    db.execute(update(Order).where(Order.id == order.id).values(is_simulated=False, customer_ref="cust_flip"))
    db.commit()

    after = client.get(f"/api/orders/{order.id}").json()

    assert before["is_simulated"] is True and after["is_simulated"] is False
    assert (
        [p["provider_kind"] for p in after["payments"]] == [p["provider_kind"] for p in before["payments"]] == ["real"]
    )


def test_the_openapi_contract_documents_the_origin_fields_and_the_removal_of_the_old_total(client: TestClient):
    spec = client.get("/openapi.json").json()["components"]["schemas"]

    for name in (
        "PaymentOut",
        "RefundOut",
        "EntryOut",
        "VerifiedRow",
        "UnderReviewRow",
        "SeriesBucket",
        "ConsolidatedEur",
    ):
        assert "provider_kind" in spec[name]["properties"], name
        assert "provider_kind" in spec[name]["required"], f"{name}: the origin is never optional"
    assert "provider_kind" not in spec["OrderOut"]["properties"]
    assert "consolidated_eur" not in spec["SummaryOut"]["properties"]
    assert "consolidated_eur_by_origin" in spec["SummaryOut"]["properties"]
    assert "contexto" in spec["OrderOut"]["properties"]["is_simulated"].get("description", "").lower()


# --- 10 · El contrato antiguo ------


OLD_VERIFIED_KEYS = {"currency", "revenue", "refunds", "net", "captures", "refund_count"}
OLD_REVIEW_KEYS = {"currency", "classification", "received", "refunded", "outstanding", "receipts", "refund_count"}


def test_the_additive_fields_of_the_old_contract_are_still_there_and_the_one_that_mixed_origins_is_gone(
    db: Session, client: TestClient
):
    origin_world(db, ("mock",))
    duplicate_pair(db, MockPaymentProvider(), new_order(db, "Dup", "sim_dup"))

    body = client.get("/api/revenue/summary").json()

    assert OLD_VERIFIED_KEYS < set(body["verified"][0]) and OLD_REVIEW_KEYS < set(body["under_review"][0])
    assert {
        "period",
        "entries",
        "verified",
        "under_review",
        "pending_evidence",
        "non_aggregable_currencies",
        "scope",
    } <= set(body)
    assert "consolidated_eur" not in body, "an old reader that wanted this figure fails instead of reading a mixed one"


def test_over_http_reading_by_origin_writes_nothing(db: Session, client: TestClient, engine):
    from sqlalchemy import event as sa_event

    origin_world(db, ORIGINS)
    statements: list[str] = []
    sa_event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))

    for path in ("summary", "summary?provider_kind=mock", "entries?provider_kind=real", "series?provider_kind=sandbox"):
        assert client.get(f"/api/revenue/{path}").status_code == 200

    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert statements and writes == [], writes
    assert db.scalar(select(Payment.provider_kind).limit(1)) in ORIGINS
