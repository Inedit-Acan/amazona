"""El comando para crear un pedido de prueba desde la consola (Milestone 44, ADR 0028).

Pasa por `OrderService`, como la API: mismas reglas y mismas validaciones. No lleva datos personales: en una
simulación genera una referencia `sim_…`. Exige `AMAZONA_BOOTSTRAP=1` como el resto de comandos que escriben.
"""

import pytest
from order_test_support import add_product, add_quote, add_supplier, make_engine, session_factory
from sqlalchemy.orm import Session

from app import cli
from app.core.errors import ValidationError
from app.db.models.audit import AuditLog
from app.db.models.order import Order


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_it_creates_a_simulated_order_with_a_generated_opaque_reference(db: Session):
    product = add_product(db)

    order = cli.create_test_order(db, product_id=product.id, quantity=3, unit_price="19.99")

    assert order.customer_ref.startswith("sim_") and "@" not in order.customer_ref
    assert order.is_simulated is True and order.status == "AWAITING_PAYMENT"
    assert str(order.amount_due).startswith("59.97")
    assert db.query(AuditLog).filter_by(action="order.created").one().actor.startswith("cli:")


def test_it_uses_the_quote_and_a_declared_cost_like_the_api(db: Session):
    product = add_product(db)
    quote = add_quote(db, product, add_supplier(db), unit_price=8.0, currency="EUR")

    order = cli.create_test_order(
        db, product_id=product.id, quantity=1, unit_price="25.00", quote_id=quote.id, unit_cost="7.50"
    )

    assert order.items[0].cost_provenance == "declared" and str(order.items[0].unit_cost).startswith("7.5")
    assert order.items[0].supplier_quote_id == quote.id


def test_it_refuses_what_the_service_refuses(db: Session):
    product = add_product(db)

    with pytest.raises(ValidationError):
        cli.create_test_order(db, product_id=product.id, quantity=1, unit_price="12.345")
    with pytest.raises(ValidationError, match="sim_"):
        cli.create_test_order(db, product_id=product.id, quantity=1, unit_price="10.00", customer_ref="customer-1")
    assert db.query(Order).count() == 0


def test_creating_a_test_order_needs_the_bootstrap_flag(monkeypatch, capsys):
    monkeypatch.delenv(cli.BOOTSTRAP_ENV, raising=False)

    status = cli.main(["create-test-order", "--product-id", "x", "--quantity", "1", "--unit-price", "5.00"])

    assert status == 2
    assert "AMAZONA_BOOTSTRAP=1" in capsys.readouterr().err


def test_the_command_asks_for_the_fields_it_needs():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["create-test-order", "--product-id", "x"])
    args = parser.parse_args(
        ["create-test-order", "--product-id", "x", "--quantity", "2", "--unit-price", "5.00", "--currency", "EUR"]
    )
    assert args.quantity == 2 and args.unit_price == "5.00" and args.customer_ref is None
