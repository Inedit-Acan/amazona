"""Ninguna tabla del núcleo de pedidos puede guardar datos personales (Milestone 44, ADR 0028 §8).

El modelo no puede guardar un nombre, un email, un teléfono, una dirección ni datos fiscales **ni por accidente**:
ninguna columna se llama como uno. La lista de tablas crece con cada migración de M44; las que todavía no existen
se saltan, y el día que existan quedan cubiertas sin tocar esta prueba.
"""

import pytest

import app.db.models  # noqa: F401 - registra todas las tablas en el metadata
from app.db.base import Base

M44_TABLES = (
    "orders",
    "order_items",
    "payments",
    "payment_events",
    "refunds",
    "fulfillments",
    "fulfillment_items",
)

#: Fragmentos que delatan un dato personal. `customer_ref` es la única referencia a un cliente y es opaca.
PERSONAL = (
    "email",
    "phone",
    "mobile",
    "address",
    "street",
    "postcode",
    "zip",
    "first_name",
    "last_name",
    "full_name",
    "surname",
    "birth",
    "tax_id",
    "vat_number",
    "nif",
    "dni",
    "passport",
    "iban",
    "card",
    "ip_address",
    "user_agent",
)

#: Cuando una columna se llama exactamente así es un identificador del dominio, no un dato personal.
ALLOWED_EXACT = {"customer_ref"}


@pytest.mark.parametrize("table", [t for t in M44_TABLES if t in Base.metadata.tables])
def test_no_column_is_named_like_personal_data(table):
    for column in Base.metadata.tables[table].columns:
        if column.name in ALLOWED_EXACT:
            continue
        assert not any(word in column.name for word in PERSONAL), f"{table}.{column.name} looks like personal data"
        assert column.name != "name", f"{table}.name would hold a person's name"


def test_the_only_reference_to_a_customer_is_opaque_and_bounded():
    column = Base.metadata.tables["orders"].columns["customer_ref"]

    assert column.type.length == 64
    checks = {c.name for c in Base.metadata.tables["orders"].constraints if c.name}
    assert "ck_orders_customer_ref_not_an_email" in checks and "ck_orders_simulation_prefix" in checks


def test_no_other_table_refers_to_a_customer():
    for name, table in Base.metadata.tables.items():
        if name in M44_TABLES and name != "orders":
            assert "customer_ref" not in table.columns, f"{name} duplicates the customer reference"
