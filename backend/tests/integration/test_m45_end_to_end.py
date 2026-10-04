"""El recorrido extremo a extremo de M45, sobre un PostgreSQL efímero (Milestone 45, ADR 0028–0030).

Cada pieza de M44 y de M45 tiene sus pruebas. Lo que no tenía **nadie** es el recorrido entero, cosido:

    señal de investigación → objetivo → proyecto y decisión → pedido → intento de cobro → evento de pago verificado
    → registro de ingresos → fulfillment (compra, envío, entrega) → reconciliación → lo que leen el Panel, Finanzas
    y Proyectos

Se hace **una vez** (el fixture `journey`), por la API HTTP como lo haría el Control Center, con **un mundo de dinero
que incluye lo incómodo a propósito**: un cobro duplicado, uno de otro importe, uno en otra moneda, un reembolso
parcial, otro que no cabe, un evento que no es de nadie, un evento que contradice a otro, un resultado desconocido y un
proceso que muere entre guardar un evento y aplicarlo. Después, cada prueba afirma **una** frase concreta sobre ese
mundo, con **cifras escritas a mano** (no calculadas con el código que se prueba).

Lo que el recorrido no inventa: no hay proveedor real (la guarda de `conftest.py` lo hace cumplir), no hay Supabase (la
base es `amazona_test_<uuid>` en un PostgreSQL local, y se borra al terminar) y nadie escribe una fila de dinero a
mano: todo entra por las puertas que existen (la API, el webhook firmado y los servicios).

Una verdad del modelo que esta prueba **documenta** y no oculta: un proyecto del Director ejecutivo **no está enlazado**
a un producto ni a un pedido. Por eso la cadena «señal → proyecto» se sigue por correlación y por el producto
investigado, y por eso Proyectos **no puede** mostrar ingresos: ningún dato los une (decisión D1 del propietario).
"""

import copy
import datetime
import json
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from m45_invariants_test_support import check_everything
from order_test_support import add_quote, add_supplier, create_order, line, session_factory
from payment_test_support import (
    ScriptedPaymentProvider,
    deliver,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.models.external_action import ExternalAction
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.product import Product
from app.db.models.revenue import RevenueLedgerEntry
from app.db.session import get_db
from app.main import app
from app.money.money import Money
from app.payments.port import PaymentEventType
from app.payments.providers.simulated import PROVIDER_NAME, SimulatedPaymentProvider
from app.payments.service import PaymentService
from app.reconciliation.actions import ActionReconciler
from app.reconciliation.events import EventReconciler

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
EXPIRED = PaymentEventType.PAYMENT_EXPIRED
REFUND_SUCCEEDED = PaymentEventType.REFUND_SUCCEEDED

CEO_CONTEXT = {
    "supplier_sourcing": {"unit_cost": 5.0, "lead_time_days": 20, "supplier_verified": True},
    "finance_validation": {
        "unit_cost": 5.0,
        "sale_price": 20.0,
        "monthly_unit_sales": 300,
        "monthly_fixed_costs": 500.0,
    },
    "legal_validation": {"restricted_category": False},
}


# --- Gestos HTTP ------------------------------------------------------------------------------------------------------


class Chain:
    """Lo que hace el Control Center, por HTTP: pedidos, cobros, webhooks, reembolsos y fulfillments."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        #: Cada petición que produce un efecto, con su clave: la prueba de idempotencia las repite todas.
        self.intents: list[tuple[str, dict]] = []
        #: Cada webhook entregado: la prueba de entregas repetidas los repite todos.
        self.webhooks: list[tuple[dict, bytes]] = []

    def post(self, path: str, *, key: str, body: dict | None = None) -> object:
        self.intents.append((path, {"json": body, "headers": {"Idempotency-Key": key}}))
        return self.client.post(path, json=body, headers={"Idempotency-Key": key})

    def order(
        self,
        product_id: str,
        *,
        key: str,
        quantity: int,
        price: str,
        currency: str = "EUR",
        quote_id: str | None = None,
        cost: str | None = None,
    ) -> dict:
        order_line = {
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": {"amount": price, "currency": currency},
        }
        if quote_id is not None:
            order_line["supplier_quote_id"] = quote_id
            order_line["declared_unit_cost"] = {"amount": cost, "currency": currency}
        body = {"customer_ref": f"sim_{key}", "market": "eu", "lines": [order_line]}
        response = self.post("/api/orders", key=key, body=body)
        assert response.status_code == 201, response.text
        return response.json()

    def attempt(self, order_id: str, *, key: str) -> dict:
        response = self.post(f"/api/orders/{order_id}/payments", key=key)
        assert response.status_code == 201, response.text
        return response.json()

    def event(
        self,
        kind: PaymentEventType,
        payment: dict,
        *,
        amount: str | None = None,
        currency: str = "EUR",
        event_id: str | None = None,
        refund: dict | None = None,
        unmatched: bool = False,
    ):
        provider = SimulatedPaymentProvider(operations={})
        money = Money.of(amount, currency) if amount is not None else None
        headers, raw = provider.simulate_event(
            kind,
            provider_payment_ref=None if unmatched else payment["provider_payment_ref"],
            provider_refund_ref=refund["provider_refund_ref"] if refund else None,
            client_reference=None if unmatched else (refund["id"] if refund else payment["id"]),
            amount=money,
            event_id=event_id,
        )
        self.webhooks.append((headers, raw))
        return self.client.post(f"/api/payments/webhooks/{PROVIDER_NAME}", content=raw, headers=headers)

    def capture(self, payment: dict, amount: str, **kwargs):
        return self.event(SUCCEEDED, payment, amount=amount, **kwargs)

    def refund(self, order_id: str, payment: dict, amount: str, *, key: str):
        body = {
            "payment_id": payment["id"],
            "amount": {"amount": amount, "currency": "EUR"},
            "reason": "customer_request",
        }
        return self.post(f"/api/orders/{order_id}/refunds", key=key, body=body)


def _frontend_reads(client: TestClient) -> dict:
    """Las lecturas que hacen las tres pantallas, tal cual (`lib/api.ts`)."""
    reads = {
        "summary": client.get("/api/revenue/summary"),
        "series": client.get("/api/revenue/series", params={"granularity": "day"}),
        "entries": client.get("/api/revenue/entries", params={"limit": 3}),
        "orders": client.get("/api/orders", params={"limit": 2}),
        "projects": client.get("/api/projects"),
        "status": client.get("/api/reconciliation/status"),
    }
    assert {name: r.status_code for name, r in reads.items()} == {name: 200 for name in reads}
    return {name: r.json() for name, r in reads.items()}


# --- El recorrido ----------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def journey():
    with ephemeral_postgres() as engine:
        factory = session_factory(engine)

        def override_get_db():
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app, raise_server_exceptions=False)
        try:
            yield _run_journey(client, factory, engine)
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_settings, None)


def _run_journey(client: TestClient, factory, engine) -> SimpleNamespace:
    chain = Chain(client)
    j = SimpleNamespace(client=client, factory=factory, engine=engine, chain=chain)

    # 1 · La señal: una investigación, con las señales simuladas del proveedor de demostración.
    research = client.post(
        "/api/research/runs", json={"category": "home", "max_results": 3}, headers={"Idempotency-Key": "r-1"}
    )
    assert research.status_code == 201, research.text
    j.research = research.json()
    assert j.research["candidates"], "a research run with no candidate leaves nothing to follow"
    top = j.research["candidates"][0]
    j.product_id = top["product_id"]

    # 2 · El proyecto y la decisión del Director ejecutivo, con lo que la señal dijo.
    context = {
        "product_validation": {
            "estimated_monthly_searches": round(top["data"]["demand_signal"] * 15000),
            "competition_level": top["data"]["competition_level"],
        },
        **CEO_CONTEXT,
    }
    objective = client.post(
        "/api/objectives",
        json={"title": f"Validate {top['name']}", "created_by": "owner@amazona.local", "context": context},
    )
    assert objective.status_code == 201, objective.text
    ran = client.post(f"/api/objectives/{objective.json()['id']}/run")
    assert ran.status_code == 200, ran.text
    j.decision = ran.json()
    j.project_id = j.decision["project_id"]

    # 3 · Los pedidos. Comprar exige un coste conocido (un coste desconocido no es cero): el pedido I lo declara.
    with factory() as db:
        supplier = add_supplier(db)
        quote = add_quote(db, db.get(Product, j.product_id), supplier)
        j.quote_id = quote.id
    j.a = chain.order(j.product_id, key="o-a", quantity=2, price="25.00")  # 50.00 EUR: un cobro normal
    j.b = chain.order(j.product_id, key="o-b", quantity=1, price="30.00")  # 30.00 EUR: un cobro duplicado
    j.c = chain.order(j.product_id, key="o-c", quantity=3, price="10.00", currency="USD")  # 30.00 USD
    j.d = chain.order(j.product_id, key="o-d", quantity=1, price="20.00")  # 20.00 EUR: reembolsos y fulfillment
    j.e = chain.order(j.product_id, key="o-e", quantity=1, price="40.00")  # 40.00 EUR: capturan 12.50
    j.f = chain.order(j.product_id, key="o-f", quantity=1, price="10.00")  # se cancela sin cobrar
    j.i = chain.order(
        j.product_id, key="o-i", quantity=1, price="18.00", quote_id=j.quote_id, cost="6.00"
    )  # 18.00 EUR: fulfillment
    cancelled = chain.post(f"/api/orders/{j.f['id']}/cancel", key="cancel-f")
    assert cancelled.status_code == 200, cancelled.text

    # 4 · Cobros y eventos verificados, por la puerta del webhook.
    j.pay_a = chain.attempt(j.a["id"], key="p-a")
    assert chain.capture(j.pay_a, "50.00", event_id="evt_a_ok").status_code == 200
    j.conflict_status = chain.capture(j.pay_a, "49.00", event_id="evt_a_ok").status_code  # mismo id, otro contenido
    j.second_capture_status = chain.capture(
        j.pay_a, "49.00", event_id="evt_a_other"
    ).status_code  # otro id, otro importe

    j.pay_b1 = chain.attempt(j.b["id"], key="p-b1")
    assert chain.event(EXPIRED, j.pay_b1, event_id="evt_b1_expired").status_code == 200
    j.pay_b2 = chain.attempt(j.b["id"], key="p-b2")
    assert chain.capture(j.pay_b2, "30.00", event_id="evt_b2_ok").status_code == 200
    assert chain.capture(j.pay_b1, "30.00", event_id="evt_b1_late").status_code == 200  # el cobro tardío del primero

    j.pay_c = chain.attempt(j.c["id"], key="p-c")
    assert chain.capture(j.pay_c, "30.00", currency="USD", event_id="evt_c_ok").status_code == 200

    j.pay_d = chain.attempt(j.d["id"], key="p-d")
    assert chain.capture(j.pay_d, "20.00", event_id="evt_d_ok").status_code == 200

    j.pay_e = chain.attempt(j.e["id"], key="p-e")
    assert chain.capture(j.pay_e, "12.50", event_id="evt_e_ok").status_code == 200

    j.pay_i = chain.attempt(j.i["id"], key="p-i")
    assert chain.capture(j.pay_i, "18.00", event_id="evt_i_ok").status_code == 200

    j.unmatched_status = chain.capture(j.pay_a, "99.00", event_id="evt_nobody", unmatched=True).status_code

    # 5 · Reembolsos: dos que caben, uno que no.
    j.refund_1 = chain.refund(j.d["id"], j.pay_d, "8.00", key="rf-1").json()
    assert (
        chain.event(REFUND_SUCCEEDED, j.pay_d, amount="8.00", refund=j.refund_1, event_id="evt_rf1").status_code == 200
    )
    j.refund_2 = chain.refund(j.d["id"], j.pay_d, "5.00", key="rf-2").json()
    assert (
        chain.event(REFUND_SUCCEEDED, j.pay_d, amount="5.00", refund=j.refund_2, event_id="evt_rf2").status_code == 200
    )
    too_much = chain.refund(j.d["id"], j.pay_d, "8.00", key="rf-3")  # quedan 7.00
    j.refund_too_much_status = too_much.status_code
    j.refund_too_much_detail = too_much.json().get("detail", "")

    # 6 · Fulfillment. Un pedido con dinero devuelto NO se reparte (regla del dominio: alguien tiene que mirarlo), y uno
    # pagado entero sí: repartir, comprar, enviar y entregar.
    item_d = client.get(f"/api/orders/{j.d['id']}").json()["items"][0]
    j.refunded_fulfilment_status = chain.post(
        f"/api/orders/{j.d['id']}/fulfillments",
        key="ful-d",
        body={"lines": [{"order_item_id": item_d["id"], "quantity": 1}]},
    ).status_code
    item_i = client.get(f"/api/orders/{j.i['id']}").json()["items"][0]
    made = chain.post(
        f"/api/orders/{j.i['id']}/fulfillments",
        key="ful-i",
        body={"lines": [{"order_item_id": item_i["id"], "quantity": 1}]},
    )
    assert made.status_code == 201, made.text
    j.fulfillment = made.json()
    assert chain.post(f"/api/fulfillments/{j.fulfillment['id']}/purchase", key="buy-i").status_code == 200
    assert chain.post(f"/api/fulfillments/{j.fulfillment['id']}/ship", key="ship-i").status_code == 200
    assert client.post(f"/api/fulfillments/{j.fulfillment['id']}/complete").status_code == 200

    # 7 · Lo que solo ocurre en el mundo real: un proceso que muere entre guardar un evento y aplicarlo (pedido H), y
    # un proveedor que ejecutó y cuya respuesta se perdió (pedido G). Por los servicios, con proveedores con guion.
    scripted = ScriptedPaymentProvider()
    with factory() as db:
        product = db.get(Product, j.product_id)
        order_h = create_order(db, line(product, quantity=1, unit_price="15.00"), customer_ref="sim_h")
        order_g = create_order(db, line(product, quantity=1, unit_price="22.00"), customer_ref="sim_g")
        j.h_id, j.g_id = order_h.id, order_g.id
        payment_h = start_attempt(db, order_h, scripted)
        j.pay_h_id = payment_h.id

        real_apply = PaymentService.apply

        def died(self, event_id):
            raise KeyboardInterrupt("the process died between storing the event and applying it")

        PaymentService.apply = died  # type: ignore[method-assign]
        try:
            with pytest.raises(KeyboardInterrupt):
                deliver(db, scripted, SUCCEEDED, payment_h)
        finally:
            PaymentService.apply = real_apply  # type: ignore[method-assign]
        db.rollback()

        unknown_provider = ScriptedPaymentProvider("timeout_after")
        payment_g = start_attempt(db, order_g, unknown_provider)
        j.pay_g_id = payment_g.id
        j.unknown_provider = unknown_provider
    j.scripted = scripted

    # 8 · Antes de reconciliar, lo que había.
    with factory() as db:
        j.h_event_before = (
            db.scalars(select(PaymentEvent).where(PaymentEvent.client_reference == j.pay_h_id)).one().processing_status
        )
        j.g_action_before = _unknown_actions(db)

    # 9 · La reconciliación programada: eventos y acciones, dos veces (la segunda no debe mover nada).
    j.reports = []
    for _ in range(2):
        with factory() as db:
            events = EventReconciler(db, older_than=datetime.timedelta(seconds=-1), max_attempts=5).sweep()
        with factory() as db:
            actions = ActionReconciler(db, older_than=datetime.timedelta(seconds=-1)).sweep()
        j.reports.append((events, actions))
    with factory() as db:
        j.g_action_after = _unknown_actions(db)
        j.h_event_after = (
            db.scalars(select(PaymentEvent).where(PaymentEvent.client_reference == j.pay_h_id)).one().processing_status
        )

    j.reads = _frontend_reads(client)
    return j


def _unknown_actions(db) -> dict[str, str]:
    return {
        a.id: a.status for a in db.scalars(select(ExternalAction).where(ExternalAction.status == "UNKNOWN_OUTCOME"))
    }


def _dec(value) -> Decimal:
    return Decimal(str(value))


# --- 1 · La cadena llegó hasta el final ---------------------------------------------------------------------------


def test_the_chain_runs_from_a_signal_to_the_screens(journey):
    j = journey
    assert j.research["candidates"][0]["data"]["demand_signal"] is not None, "the research brought a signal"
    assert j.decision["status"] in {"GO", "REVIEW", "NO_GO", "HUMAN_APPROVAL"}
    assert j.client.get(f"/api/projects/{j.project_id}").json()["id"] == j.project_id
    tasks = j.client.get("/api/tasks", params={"project_id": j.project_id}).json()
    assert tasks and all(t["status"] == "COMPLETED" for t in tasks)

    orders = {o["id"]: o for o in j.client.get("/api/orders", params={"limit": 50}).json()["items"]}
    assert orders[j.a["id"]]["status"] == "PAID"
    assert orders[j.d["id"]]["status"] == "PAID" and orders[j.d["id"]]["fulfillments"] == []
    assert j.refunded_fulfilment_status == 409, (
        "an order with money refunded is not fulfilled until someone looks at it"
    )
    assert [f["status"] for f in orders[j.i["id"]]["fulfillments"]] == ["COMPLETED"]
    assert orders[j.e["id"]]["status"] == "AWAITING_PAYMENT", "a capture of another amount does not pay the order"
    assert orders[j.f["id"]]["status"] == "CANCELLED"
    assert orders[j.h_id]["status"] == "PAID", "the reconciler applied the event the process died on"
    assert orders[j.g_id]["status"] == "AWAITING_PAYMENT", "an unknown outcome pays nothing"
    assert j.reads["summary"]["entries"] == 10


def test_every_order_in_the_journey_is_marked_simulated_and_the_ledger_does_not_say_otherwise(journey):
    j = journey
    for order in j.client.get("/api/orders", params={"limit": 50}).json()["items"]:
        assert order["is_simulated"] is True, order["id"]
    # El registro habla de hechos de pago verificados, no de dinero «real»: ninguna clave ni valor lo afirma.
    for name in ("summary", "series", "entries"):
        text_of = json.dumps(j.reads[name])
        assert not re.search(r'"[^"]*(is_real|real_money|real_revenue|non_simulated)[^"]*"\s*:', text_of), name
        assert not re.search(r'"(REAL|real)"', text_of), f"{name} labels something as REAL"
    assert j.reads["summary"]["scope"]["is_accounting_ledger"] is False


# --- 2 · Ninguna entrada sin un hecho verificado ----------------------------------------------------------------


def test_no_ledger_entry_exists_without_a_valid_applied_payment_event(journey):
    with journey.factory() as db:
        orphans = db.execute(
            text(
                "SELECT l.id FROM revenue_ledger_entries l LEFT JOIN payment_events e ON e.id = l.payment_event_id "
                "WHERE e.id IS NULL OR e.processing_status <> 'APPLIED' "
                "OR (l.kind = 'CAPTURE' AND e.event_type <> 'payment.succeeded') "
                "OR (l.kind = 'REFUND' AND e.event_type <> 'refund.succeeded')"
            )
        ).all()
        assert orphans == []
        assert db.scalar(select(func.count()).select_from(RevenueLedgerEntry)) == 10
        assert check_everything(db) == [], "the independent oracle finds the whole journey coherent"


# --- 3 · Un cobro verificado duplicado no duplica el ingreso -------------------------------------------------------


def test_delivering_every_webhook_again_changes_nothing(journey):
    j = journey
    with j.factory() as db:
        before = _snapshot(db)
    for headers, raw in j.chain.webhooks:
        response = j.client.post(f"/api/payments/webhooks/{PROVIDER_NAME}", content=raw, headers=headers)
        assert response.status_code in (200, 409), (response.status_code, response.text)
    with j.factory() as db:
        assert _snapshot(db) == before, "a repeated delivery moved the ledger, a payment or an order"
        assert db.scalar(select(func.count()).select_from(RevenueLedgerEntry)) == 10
        assert check_everything(db) == []


def _snapshot(db) -> dict:
    db.expire_all()
    return {
        "entries": sorted((e.id, str(e.amount), e.classification) for e in db.scalars(select(RevenueLedgerEntry))),
        "payments": sorted(
            (p.id, p.status, str(p.captured_amount), str(p.refunded_amount)) for p in db.scalars(select(Payment))
        ),
        "orders": sorted((o.id, o.status) for o in db.scalars(select(Order))),
        "events": sorted((e.id, e.processing_status) for e in db.scalars(select(PaymentEvent))),
    }


# --- 4 · Lo que no es ingreso confirmado no lo es -----------------------------------------------------------------


def test_conflict_unmatched_and_duplicate_money_is_never_confirmed_revenue(journey):
    j = journey
    assert j.conflict_status == 409, "the same event id with another content is refused"
    assert j.second_capture_status == 200
    with j.factory() as db:
        by_status: dict[str, list[PaymentEvent]] = {}
        for event_row in db.scalars(select(PaymentEvent)):
            by_status.setdefault(event_row.processing_status, []).append(event_row)
        assert {e.provider_event_id for e in by_status["CONFLICT"]} == {"evt_a_other"}
        assert {e.provider_event_id for e in by_status["UNMATCHED"]} == {"evt_nobody"}
        caused = {e.payment_event_id for e in db.scalars(select(RevenueLedgerEntry))}
        for status in ("CONFLICT", "UNMATCHED"):
            assert not {e.id for e in by_status[status]} & caused, f"a {status} event has an entry"

        duplicate = db.get(Payment, j.pay_b1["id"])
        assert duplicate.status == "DUPLICATE_CAPTURE" and _dec(duplicate.captured_amount) == Decimal("30")

    summary = j.reads["summary"]
    eur = next(row for row in summary["verified"] if row["currency"] == "EUR")
    assert (_dec(eur["revenue"]), _dec(eur["refunds"]), _dec(eur["net"])) == (
        Decimal("133"),
        Decimal("13"),
        Decimal("120"),
    )
    review = {(r["currency"], r["classification"]): r for r in summary["under_review"]}
    assert _dec(review[("EUR", "DUPLICATE_RECEIPT")]["received"]) == Decimal("30")
    assert _dec(review[("EUR", "MISMATCH_RECEIPT")]["received"]) == Decimal("12.5")
    pending = {(r["currency"], r["event_type"]): r for r in summary["pending_evidence"]["by_currency"]}
    assert _dec(pending[("EUR", "payment.succeeded")]["amount"]) == Decimal("148"), (
        "49.00 conflicting + 99.00 unmatched"
    )
    assert _dec(summary["consolidated_eur"]["revenue"]) == Decimal("133"), "the headline excludes review and pending"


def test_a_currency_is_never_added_to_another(journey):
    summary = journey.reads["summary"]
    verified = {row["currency"]: row for row in summary["verified"]}
    assert set(verified) == {"EUR", "USD"}
    assert _dec(verified["USD"]["revenue"]) == Decimal("30")
    assert _dec(summary["consolidated_eur"]["revenue"]) == Decimal("133"), "the 30.00 USD is not in the EUR headline"
    assert [row["currency"] for row in summary["non_aggregable_currencies"]] == ["USD"]
    for row in journey.client.get("/api/revenue/entries", params={"limit": 50}).json()["items"]:
        assert row["currency"] in {"EUR", "USD"}
    with journey.factory() as db:
        for entry in db.scalars(select(RevenueLedgerEntry)):
            assert entry.currency == db.get(Payment, entry.payment_id).currency


# --- 5 · Los reembolsos no superan lo capturado ------------------------------------------------------------------


def test_a_refund_never_exceeds_what_was_captured(journey):
    j = journey
    assert j.refund_too_much_status in (409, 422), "8.00 more than the 7.00 left is refused"
    # CAPA 1, el servicio: lo rechaza ÉL, con su motivo (y no la capa de debajo ni la base de datos).
    assert "left to refund" in j.refund_too_much_detail, j.refund_too_much_detail
    assert "has less than" not in j.refund_too_much_detail, "the service refused before touching the payment"
    with j.factory() as db:
        payment = db.get(Payment, j.pay_d["id"])
        assert _dec(payment.captured_amount) == Decimal("20")
        assert _dec(payment.refunded_amount) == Decimal("13") == _dec(payment.refund_committed_amount)
        assert db.scalars(select(Refund).where(Refund.payment_id == payment.id, Refund.amount == Decimal("8"))).all()
        assert len(db.scalars(select(Refund).where(Refund.payment_id == payment.id)).all()) == 2, (
            "the refused one left no row"
        )

    # CAPA 2, el `UPDATE … WHERE` que aparta el importe: por sí sola dice que no cabe y no mueve nada.
    from app.payments.ledger import reserve

    with j.factory() as db:
        assert reserve(db, j.pay_d["id"], Decimal("8.00")) is False
        db.rollback()
        assert _dec(db.get(Payment, j.pay_d["id"]).refund_committed_amount) == Decimal("13")
        assert reserve(db, j.pay_d["id"], Decimal("7.00")) is True, "lo que sí cabe se aparta"
        db.rollback()

    # CAPA 3, la base de datos: aunque el código se equivocara, no deja escribir más reembolsado que cobrado.
    with j.factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                update(Payment)
                .where(Payment.id == j.pay_d["id"])
                .values(refunded_amount=Decimal("21"), refund_committed_amount=Decimal("21"))
            )
            db.commit()
        db.rollback()


# --- 6 · Un resultado desconocido no se cierra solo ------------------------------------------------------------


def test_an_unknown_outcome_is_not_closed_by_any_reconciliation(journey):
    j = journey
    assert len(j.g_action_before) == 1, "exactly the payment whose answer was lost is unknown"
    assert j.g_action_after == j.g_action_before, "the sweeps changed an UNKNOWN_OUTCOME"
    for events, actions in j.reports:
        assert actions.released == [] and actions.marked_unknown == [], "nothing is released or invented"
        assert actions.failed == [] and events.failed == []
    with j.factory() as db:
        payment = db.get(Payment, j.pay_g_id)
        assert payment.status == "UNKNOWN_OUTCOME"
        assert db.get(Order, j.g_id).status == "AWAITING_PAYMENT"
        assert db.scalars(select(RevenueLedgerEntry).where(RevenueLedgerEntry.payment_id == payment.id)).all() == []


def test_an_external_operation_that_may_have_executed_is_not_repeated_blindly(journey):
    j = journey
    assert len(j.unknown_provider.calls) == 1, "one call went out, and no sweep sent a second"
    response = j.client.post(f"/api/orders/{j.g_id}/payments", headers={"Idempotency-Key": "p-g-new"})
    assert response.status_code in (409, 423), "a new attempt over an unknown outcome is refused"
    assert len(j.unknown_provider.calls) == 1
    with j.factory() as db:
        per_reference = db.execute(
            select(ExternalAction.reference, func.count()).group_by(ExternalAction.reference).having(func.count() > 1)
        ).all()
        assert per_reference == [], "an operation exists twice for the same place"


# --- 7 · Una intención idempotente produce, como mucho, un efecto -----------------------------------------


def test_repeating_every_intent_with_its_key_produces_no_second_effect(journey):
    j = journey
    with j.factory() as db:
        before = (
            _snapshot(db),
            db.scalar(select(func.count()).select_from(ExternalAction)),
            db.scalar(select(func.count()).select_from(Fulfillment)),
            db.scalar(select(func.count()).select_from(Refund)),
        )
    assert len(j.chain.intents) >= 15
    for path, kwargs in j.chain.intents:
        response = j.client.post(path, **kwargs)
        assert response.status_code < 500, (path, response.status_code, response.text)
        if response.status_code < 300:
            assert response.headers.get("Idempotency-Replayed") == "true", f"{path} produced a second effect"
    with j.factory() as db:
        after = (
            _snapshot(db),
            db.scalar(select(func.count()).select_from(ExternalAction)),
            db.scalar(select(func.count()).select_from(Fulfillment)),
            db.scalar(select(func.count()).select_from(Refund)),
        )
    assert after == before


# --- 8 · Ningún GET escribe ----------------------------------------------------------------------------------------


def test_no_read_route_writes_anything_on_a_database_full_of_data(journey):
    j = journey
    ids = {
        "order_id": j.i["id"],
        "project_id": j.project_id,
        "product_id": j.product_id,
        "fulfillment_id": j.fulfillment["id"],
        "decision_id": j.decision["id"],
        "correlation_id": j.decision["correlation_id"],
    }
    writes: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            writes.append(statement[:100])

    with j.factory() as db:
        before = _row_counts(db)
    event.listen(j.engine, "before_cursor_execute", capture)
    try:
        paths = sorted(path for path, item in app.openapi()["paths"].items() if "get" in item)
        assert len(paths) >= 24
        reached = 0
        for path in paths:
            filled = re.sub(r"\{([^}]+)\}", lambda m: ids.get(m.group(1), "does-not-exist"), path)
            response = j.client.get(filled)
            reached += response.status_code == 200
            assert response.status_code < 500, (filled, response.status_code)
    finally:
        event.remove(j.engine, "before_cursor_execute", capture)
    assert reached >= 15, f"only {reached} read routes answered 200: the sweep is not looking at real data"
    assert writes == [], f"a GET wrote: {writes[:3]}"
    with j.factory() as db:
        assert _row_counts(db) == before, "a GET changed the number of rows"


def _row_counts(db) -> dict[str, int]:
    names = [n for n in inspect(db.get_bind()).get_table_names() if not n.startswith("alembic")]
    return {n: db.execute(text(f'SELECT count(*) FROM "{n}"')).scalar_one() for n in names}


# --- 9 · Lo que leen las pantallas es lo que hay --------------------------------------------------------------------


def test_the_paginated_routes_say_when_they_truncate_and_walking_them_visits_everything_once(journey):
    j = journey
    page = j.reads["entries"]
    assert len(page["items"]) == 3 and page["has_more"] is True and page["next_cursor"], (
        "10 entries, 3 shown, and it says so"
    )

    seen, cursor = [], None
    for _ in range(20):
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = j.client.get("/api/revenue/entries", params=params).json()
        seen += [row["id"] for row in body["items"]]
        cursor = body["next_cursor"]
        if not body["has_more"]:
            assert cursor is None
            break
    assert len(seen) == len(set(seen)) == 10

    first = j.reads["orders"]
    with j.factory() as db:
        total_orders = db.scalar(select(func.count()).select_from(Order))
    assert first["has_more"] is True and first["count"] == len(first["items"]) == 2 < total_orders
    walked, cursor = [], None
    for _ in range(20):
        body = j.client.get("/api/orders", params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        walked += [o["id"] for o in body["items"]]
        cursor = body["next_cursor"]
        if not body["has_more"]:
            break
    assert len(walked) == len(set(walked)) == total_orders == 9


def test_the_series_and_the_summary_add_up_to_the_same_money(journey):
    series = journey.reads["series"]
    summary = journey.reads["summary"]
    revenue: dict[str, Decimal] = {}
    refunds: dict[str, Decimal] = {}
    for bucket in series["buckets"]:
        revenue[bucket["currency"]] = revenue.get(bucket["currency"], Decimal(0)) + _dec(bucket["revenue"])
        refunds[bucket["currency"]] = refunds.get(bucket["currency"], Decimal(0)) + _dec(bucket["refunds"])
    for row in summary["verified"]:
        assert revenue.get(row["currency"]) == _dec(row["revenue"]), row["currency"]
        assert refunds.get(row["currency"]) == _dec(row["refunds"]), row["currency"]


def test_projects_carry_no_money_because_nothing_links_a_project_to_an_order(journey):
    j = journey
    projects = j.reads["projects"]
    assert [p["id"] for p in projects] == [j.project_id]
    assert set(projects[0]) == {"id", "objective_id", "name", "status"}, "a project exposes no revenue, cost or profit"
    assert not re.search(r"revenue|profit|margin|cost|capital|amount", json.dumps(projects), re.IGNORECASE)
    decision = j.client.get(f"/api/decisions/{j.decision['id']}").json()
    finance = next(e for e in decision["evidence"] if e["source"] == "finance_validation")
    assert "monthly_profit" in finance["data"], "the only profit a project has is a PLAN projection from the objective"
    with j.factory() as db:
        for column in inspect(db.get_bind()).get_columns("projects"):
            assert column["name"] not in {"order_id", "product_id", "revenue", "profit"}


# --- 10 · La reconciliación aplica una vez lo que quedó a medias -----------------------------------------------


def test_the_reconciler_applies_what_a_dead_process_left_half_done_exactly_once(journey):
    j = journey
    assert j.h_event_before == "RECEIVED" and j.h_event_after == "APPLIED"
    first_events = j.reports[0][0]
    second_events = j.reports[1][0]
    assert first_events.examined == 1 and first_events.outcomes == {"applied": 1}
    assert second_events.examined == 0, "the second sweep found nothing left to apply"
    with j.factory() as db:
        mine = db.scalars(select(RevenueLedgerEntry).where(RevenueLedgerEntry.payment_id == j.pay_h_id)).all()
        assert len(mine) == 1 and _dec(mine[0].amount) == Decimal("15")


def test_the_status_route_agrees_with_the_ledger_and_shows_what_is_pending(journey):
    status = journey.reads["status"]
    assert status["revenue"]["ledger"]["entries"] == 10
    assert status["revenue"]["ledger"]["divergences"]["count"] == 0
    assert status["revenue"]["pending_evidence"]["count"] == 2
    assert [u["reference"] for u in status["actions"]["unknown_outcomes"]] == [f"order_payment:{journey.pay_g_id}"]
    assert copy.deepcopy(status["actions"]["open"])["UNKNOWN_OUTCOME"]["count"] == 1
