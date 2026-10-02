"""Apoyo compartido de las pruebas de pedidos, pagos y fulfillment (Milestone 44, ADR 0028).

Módulo auxiliar de tests, **no** un test: bases de datos en memoria y los datos de partida (un producto, un
proveedor, una cotización) con los que se crea un pedido. Ningún dato es personal: el cliente es una referencia
opaca (`sim_…`).
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.money.money import Money
from app.orders.service import NewOrderLine, OrderService

#: Una simulación: todos los proveedores `MOCK` y desarrollo (`operating_in_simulation`).
SIMULATION = Settings(_env_file=None)


def make_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_product(db: Session, name: str = "Widget", category: str = "home") -> Product:
    product = Product(name=name, category=category, status="ACTIVE", created_by="test")
    db.add(product)
    db.commit()
    return product


def add_supplier(db: Session, name: str = "Acme Supplies") -> Supplier:
    supplier = Supplier(name=name)
    db.add(supplier)
    db.commit()
    return supplier


def add_quote(
    db: Session,
    product: Product,
    supplier: Supplier,
    *,
    unit_price: float | None = 8.0,
    currency: str | None = "EUR",
    provenance: str | None = "supplier_claim",
) -> SupplierQuote:
    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        unit_price=unit_price,
        currency=currency,
        provenance=provenance,
        correlation_id="corr-quote",
    )
    db.add(quote)
    db.commit()
    return quote


def line(
    product: Product,
    *,
    quantity: int = 2,
    unit_price: str = "25.00",
    currency: str = "EUR",
    quote: SupplierQuote | None = None,
    declared_cost: str | None = None,
) -> NewOrderLine:
    return NewOrderLine(
        product_id=product.id,
        quantity=quantity,
        unit_price=Money.of(unit_price, currency),
        supplier_quote_id=quote.id if quote else None,
        declared_unit_cost=Money.of(declared_cost, currency) if declared_cost is not None else None,
    )


def create_order(db: Session, *lines: NewOrderLine, customer_ref: str = "sim_customer", market: str = "eu"):
    """Un pedido en `AWAITING_PAYMENT` creado por el servicio, como en la API."""
    return OrderService(db, settings=SIMULATION).create(
        customer_ref=customer_ref, market=market, lines=list(lines), actor="test@amazona.local"
    )
