"""Crear y leer pedidos (Milestone 44, ADR 0028 §6 y §8).

Qué se prueba: que un pedido nace sin datos personales y sin inventar nada (el importe son las líneas, el coste
desconocido es desconocido), que un mismo producto puede repetirse en varias líneas, y que **no existe ninguna
función que marque un pedido como pagado**.
"""

import inspect

import pytest
from order_test_support import (
    SIMULATION,
    add_product,
    add_quote,
    add_supplier,
    create_order,
    line,
    make_engine,
    session_factory,
)
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Environment, Settings
from app.core.errors import NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.order import Order, OrderItem
from app.integrations.ports import ProviderKind
from app.money.money import Money
from app.orders import service as orders_service
from app.orders.domain import ORDER_TRANSITIONS, OrderStatus, can_transition
from app.orders.service import NewOrderLine, OrderService

REAL = Settings(_env_file=None, ads_provider=ProviderKind.REAL)


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def product(db: Session):
    return add_product(db)


# --- Un pedido nace sin inventar nada -----------------------------------------------------------


def test_an_order_is_born_awaiting_payment_and_simulated_in_a_simulation(db, product):
    order = create_order(db, line(product, quantity=2, unit_price="25.00"))

    assert order.status == OrderStatus.AWAITING_PAYMENT.value
    assert order.is_simulated is True
    assert order.paid_at is None and order.completed_at is None and order.cancelled_at is None
    assert [i.line_number for i in order.items] == [1]


def test_the_amount_due_is_exactly_the_sum_of_the_lines(db, product):
    order = create_order(
        db,
        line(product, quantity=3, unit_price="19.99"),
        line(product, quantity=1, unit_price="0.10"),
        line(product, quantity=2, unit_price="0.20"),
    )

    assert Money.of(str(order.amount_due), "EUR") == Money.of("60.47", "EUR")  # 59.97 + 0.10 + 0.40


def test_there_is_no_tax_shipping_or_discount_because_none_exists_yet(db, product):
    order = create_order(db, line(product))
    columns = {c.name for c in Order.__table__.columns}

    assert not columns & {"tax", "tax_amount", "vat", "shipping", "shipping_amount", "discount", "total"}
    assert str(order.amount_due) == str(order.items[0].line_total)


def test_an_unknown_supplier_cost_stays_unknown_not_zero(db, product):
    order = create_order(db, line(product))
    item = order.items[0]

    assert item.unit_cost is None and item.cost_provenance is None and item.cost_source is None


def test_a_cost_from_the_quote_is_used_only_when_it_is_in_the_order_currency(db, product):
    supplier = add_supplier(db)
    in_euros = add_quote(db, product, supplier, unit_price=8.5, currency="EUR")
    in_dollars = add_quote(db, product, supplier, unit_price=9.0, currency="USD")

    same = create_order(db, line(product, quote=in_euros)).items[0]
    other = create_order(db, line(product, quote=in_dollars)).items[0]

    assert Money.of(str(same.unit_cost), "EUR") == Money.of("8.50", "EUR")
    assert same.cost_provenance == "supplier_claim" and same.cost_source == f"supplier_quote:{in_euros.id}"
    assert same.supplier_id == supplier.id
    assert other.unit_cost is None, "a cost in another currency is not converted by guessing"
    assert other.supplier_id == supplier.id, "the supplier is still known"


def test_a_declared_cost_wins_over_the_quote_and_names_who_declared_it(db, product):
    quote = add_quote(db, product, add_supplier(db), unit_price=8.5, currency="EUR")

    item = create_order(db, line(product, quote=quote, declared_cost="7.25")).items[0]

    assert Money.of(str(item.unit_cost), "EUR") == Money.of("7.25", "EUR")
    assert item.cost_provenance == "declared" and item.cost_source == "manual:test@amazona.local"


def test_a_free_item_is_not_how_a_cost_is_declared_but_a_zero_cost_can_be(db, product):
    item = create_order(db, line(product, declared_cost="0.00")).items[0]

    assert item.unit_cost is not None and Money.of(str(item.unit_cost), "EUR").is_zero


# --- Identidad de las líneas ------------------------------------------------------------------


def test_the_same_product_can_be_in_several_lines_with_their_own_identity(db, product):
    supplier_a, supplier_b = add_supplier(db, "A"), add_supplier(db, "B")
    quote_a = add_quote(db, product, supplier_a, unit_price=8.0)
    quote_b = add_quote(db, product, supplier_b, unit_price=9.0)

    order = create_order(
        db,
        line(product, quantity=1, unit_price="25.00", quote=quote_a),
        line(product, quantity=1, unit_price="22.00", quote=quote_b),
        line(product, quantity=4, unit_price="25.00"),
    )

    assert [i.line_number for i in order.items] == [1, 2, 3]
    assert len({i.id for i in order.items}) == 3
    assert {i.supplier_id for i in order.items} == {supplier_a.id, supplier_b.id, None}
    assert db.query(OrderItem).filter_by(product_id=product.id).count() == 3


# --- Lo que se rechaza ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "customer_ref",
    ["ana@example.com", "Ana García", "", " ", "x" * 65, "sim_ana@example.com", "sim_a b"],
)
def test_a_customer_reference_that_could_be_personal_data_is_refused(db, product, customer_ref):
    with pytest.raises(ValidationError):
        create_order(db, line(product), customer_ref=customer_ref)
    assert db.query(Order).count() == 0


def test_in_a_simulation_every_customer_reference_starts_with_sim(db, product):
    with pytest.raises(ValidationError, match="sim_"):
        create_order(db, line(product), customer_ref="customer-77")


def test_outside_a_simulation_a_reference_cannot_pretend_to_be_a_test_one(db, product):
    service = OrderService(db, settings=REAL)

    with pytest.raises(ValidationError, match="reserved for simulations"):
        service.create(customer_ref="sim_customer", market="eu", lines=[line(product)], actor="t")

    order = service.create(customer_ref="customer-77", market="eu", lines=[line(product)], actor="t")
    assert order.is_simulated is False


def test_an_order_in_production_is_not_a_simulation(db, product):
    service = OrderService(db, settings=Settings(_env_file=None, environment=Environment.PRODUCTION))

    with pytest.raises(ValidationError, match="reserved for simulations"):
        service.create(customer_ref="sim_x", market="eu", lines=[line(product)], actor="t")


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 10_001},
        {"unit_price": "0.00"},
        {"unit_price": "12.345"},  # más decimales que un céntimo
        {"currency": "ZZZ"},
    ],
)
def test_invalid_lines_are_refused_and_nothing_is_written(db, product, bad):
    with pytest.raises(ValidationError):
        create_order(db, line(product, **bad))
    assert db.query(Order).count() == 0 and db.query(OrderItem).count() == 0


def test_every_line_of_an_order_is_in_the_same_currency(db, product):
    with pytest.raises(ValidationError, match="nothing is converted"):
        create_order(
            db, line(product, unit_price="10.00", currency="EUR"), line(product, unit_price="10.00", currency="USD")
        )


def test_an_order_needs_at_least_one_line_and_at_most_fifty(db, product):
    service = OrderService(db, settings=SIMULATION)
    with pytest.raises(ValidationError):
        service.create(customer_ref="sim_a", market="eu", lines=[], actor="t")
    with pytest.raises(ValidationError):
        service.create(customer_ref="sim_a", market="eu", lines=[line(product)] * 51, actor="t")


def test_an_unknown_product_or_a_quote_of_another_product_is_refused(db, product):
    other = add_product(db, "Other")
    quote_of_other = add_quote(db, other, add_supplier(db))

    with pytest.raises(NotFoundError):
        create_order(db, NewOrderLine(product_id="nope", quantity=1, unit_price=Money.of("5.00", "EUR")))
    with pytest.raises(ValidationError, match="another product"):
        create_order(db, line(product, quote=quote_of_other))


def test_a_declared_cost_cannot_be_negative_or_in_another_currency(db, product):
    with pytest.raises(ValidationError):
        create_order(db, line(product, declared_cost="-1.00"))
    with pytest.raises(ValidationError, match="nothing is converted"):
        create_order(
            db,
            NewOrderLine(
                product_id=product.id,
                quantity=1,
                unit_price=Money.of("5.00", "EUR"),
                declared_unit_cost=Money.of("3.00", "USD"),
            ),
        )


# --- Rastro y lectura ---------------------------------------------------------------------------------


def test_creating_an_order_leaves_an_audit_entry_without_personal_data(db, product):
    order = create_order(db, line(product))

    entry = db.query(AuditLog).filter_by(action="order.created").one()
    assert entry.resource == f"order:{order.id}" and entry.actor == "test@amazona.local"
    assert entry.after["customer_ref"] == "sim_customer" and entry.after["simulated"] is True


def test_reading_orders_never_writes(db, product):
    order = create_order(db, line(product))
    writes: list[str] = []
    event.listen(db.get_bind(), "before_cursor_execute", lambda c, cur, stmt, *a: writes.append(stmt))
    service = OrderService(db, settings=SIMULATION)
    writes.clear()

    service.get(order.id)
    service.list_page()
    service.list_page(status="PAID")

    assert not [s for s in writes if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]


def test_listing_filters_by_status_and_unknown_orders_are_not_found(db, product):
    create_order(db, line(product))
    service = OrderService(db, settings=SIMULATION)

    awaiting = service.list_page(status="AWAITING_PAYMENT")
    assert len(awaiting.orders) == 1 and awaiting.has_more is False and awaiting.next_cursor is None
    assert service.list_page(status="PAID").orders == []
    with pytest.raises(NotFoundError):
        service.get("missing")


# --- No hay ninguna manera de pagar desde aquí ---------------------------------------------------------


def test_the_order_service_has_no_way_to_mark_an_order_as_paid():
    public = {name for name, member in inspect.getmembers(OrderService, inspect.isfunction) if not name.startswith("_")}

    assert public == {"create", "get", "list_page", "cancel"}, "creating, reading and cancelling: never paying"
    source = inspect.getsource(orders_service)
    assert "OrderStatus.PAID" not in source and "paid_at =" not in source


def test_the_transition_table_only_reaches_paid_from_awaiting_payment():
    for current, targets in ORDER_TRANSITIONS.items():
        for target in OrderStatus:
            assert can_transition(current, target) is (target in targets)
    reaching_paid = [s for s, targets in ORDER_TRANSITIONS.items() if OrderStatus.PAID in targets]
    assert reaching_paid == [OrderStatus.AWAITING_PAYMENT]
    assert not ORDER_TRANSITIONS[OrderStatus.COMPLETED] and not ORDER_TRANSITIONS[OrderStatus.CANCELLED]
