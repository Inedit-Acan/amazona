"""La migración de pedidos y líneas (Milestone 44, ADR 0028), ejecutada de verdad.

Lo que solo una migración ejecutada demuestra: que crea lo mismo que declara el modelo, que las garantías que
respaldan la base de datos existen (la referencia de cliente opaca, el prefijo `sim_`, la asignación acotada) y que
**no hay unicidad por producto** en las líneas: un mismo producto puede estar en varias.
"""

import pytest
import sqlalchemy as sa
from m44_migration_test_support import (
    apply_prerequisites,
    assert_migration_matches_model,
    assert_rls_pattern,
    load_migration,
    new_connection,
    run,
)

FILE = "f6a1c8d3e925_orders_and_items.py"
TABLES = ("orders", "order_items")


@pytest.fixture()
def connection():
    engine = new_connection()
    with engine.connect() as conn:
        apply_prerequisites(conn, "products", "suppliers", "supplier_quotes")
        yield conn
    engine.dispose()


def migrate(conn, direction: str = "upgrade") -> None:
    run(conn, load_migration(FILE), direction)


def insert_order(conn, **overrides) -> None:
    values = {
        "id": "o-1",
        "customer_ref": "sim_one",
        "market": "eu",
        "currency": "EUR",
        "amount_due": 25.0,
        "status": "AWAITING_PAYMENT",
        "is_simulated": True,
        "correlation_id": "corr-1",
        "created_at": "2026-10-02 10:00:00",
        "updated_at": "2026-10-02 10:00:00",
    }
    values.update(overrides)
    conn.execute(
        sa.text(f"INSERT INTO orders ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"), values
    )


def insert_item(conn, **overrides) -> None:
    values = {
        "id": "i-1",
        "order_id": "o-1",
        "line_number": 1,
        "product_id": "p-1",
        "quantity": 2,
        "allocated_quantity": 0,
        "unit_price": 12.5,
        "line_total": 25.0,
        "created_at": "2026-10-02 10:00:00",
        "updated_at": "2026-10-02 10:00:00",
    }
    values.update(overrides)
    conn.execute(
        sa.text(f"INSERT INTO order_items ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"), values
    )


def seed_product(conn) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO products (id, name, category, status, created_by, source, created_at, updated_at) "
            "VALUES ('p-1', 'Widget', 'home', 'ACTIVE', 'test', 'test', '2026-10-02', '2026-10-02')"
        )
    )


def seed(conn) -> None:
    seed_product(conn)
    insert_order(conn)


# --- La cadena y subir/bajar -----------------------------------------------------------------


def test_the_revision_chains_after_the_database_identity_guards():
    module = load_migration(FILE)

    assert module.revision == "f6a1c8d3e925"
    assert module.down_revision == "e1b8d4a62f37"


def test_upgrade_creates_both_tables_and_downgrade_removes_them(connection):
    migrate(connection)
    assert set(TABLES) <= set(sa.inspect(connection).get_table_names())

    migrate(connection, "downgrade")

    assert not set(TABLES) & set(sa.inspect(connection).get_table_names())


def test_it_can_be_applied_again_after_a_downgrade(connection):
    migrate(connection)
    migrate(connection, "downgrade")

    migrate(connection)

    assert set(TABLES) <= set(sa.inspect(connection).get_table_names())


def test_the_migration_creates_what_the_model_declares(connection):
    migrate(connection)

    assert_migration_matches_model(connection, TABLES)


# --- Lo que garantiza la base de datos ----------------------------------------------------------


def test_a_customer_reference_cannot_be_an_email(connection):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_order(connection, customer_ref="sim_ana@example.com")


def test_a_simulated_order_must_use_the_simulation_prefix_and_a_real_one_must_not(connection):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_order(connection, id="o-2", customer_ref="customer-77", is_simulated=True)
    with pytest.raises(sa.exc.IntegrityError):
        insert_order(connection, id="o-3", customer_ref="sim_real_looking", is_simulated=False)
    insert_order(connection, id="o-4", customer_ref="customer-77", is_simulated=False)


@pytest.mark.parametrize("status", ["PENDING", "PAYMENT_FAILED", "paid"])
def test_an_order_can_only_be_in_a_known_state(connection, status):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_order(connection, status=status)


@pytest.mark.parametrize("amount", [0, -5])
def test_an_order_must_charge_something(connection, amount):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_order(connection, amount_due=amount)


def test_a_line_number_is_unique_within_an_order(connection):
    migrate(connection)
    seed(connection)
    insert_item(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, id="i-2", product_id="p-1")


def test_the_same_product_can_appear_in_several_lines_of_an_order(connection):
    """Variante, proveedor, cotización, precio, lote, división logística: el producto no es la identidad de la línea."""
    migrate(connection)
    seed(connection)

    insert_item(connection, id="i-1", line_number=1, unit_price=12.5, line_total=25.0)
    insert_item(connection, id="i-2", line_number=2, unit_price=11.0, line_total=22.0)
    insert_item(connection, id="i-3", line_number=3, quantity=1, unit_price=12.5, line_total=12.5)

    count = connection.execute(sa.text("SELECT count(*) FROM order_items WHERE product_id = 'p-1'")).scalar_one()
    assert count == 3


def test_a_line_cannot_allocate_more_units_than_it_has(connection):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, quantity=2, allocated_quantity=3)
    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, id="i-2", allocated_quantity=-1)


@pytest.mark.parametrize("overrides", [{"quantity": 0}, {"unit_price": 0}, {"line_total": 0}, {"line_number": 0}])
def test_a_line_needs_a_positive_quantity_price_and_number(connection, overrides):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, **overrides)


def test_an_unknown_cost_is_null_and_a_known_cost_names_who_says_so(connection):
    migrate(connection)
    seed(connection)

    insert_item(connection, id="i-1", line_number=1)  # desconocido: ni coste ni procedencia
    insert_item(connection, id="i-2", line_number=2, unit_cost=3.0, cost_provenance="declared")
    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, id="i-3", line_number=3, unit_cost=3.0)  # un coste sin quien lo sostenga
    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, id="i-4", line_number=4, cost_provenance="declared")  # procedencia sin coste
    with pytest.raises(sa.exc.IntegrityError):
        insert_item(connection, id="i-5", line_number=5, unit_cost=-1.0, cost_provenance="declared")


def test_the_migration_does_not_touch_other_tables(connection):
    connection.execute(sa.text("CREATE TABLE bystander (id INTEGER PRIMARY KEY, note TEXT)"))
    connection.execute(sa.text("INSERT INTO bystander (id, note) VALUES (1, 'unchanged')"))

    migrate(connection)
    migrate(connection, "downgrade")

    assert connection.execute(sa.text("SELECT note FROM bystander")).scalar_one() == "unchanged"


def test_no_table_carries_personal_data_columns(connection):
    """El modelo no puede guardar datos personales ni por accidente: ninguna columna se llama como uno."""
    migrate(connection)
    forbidden = ("email", "phone", "address", "first_name", "last_name", "full_name", "tax_id", "dni", "iban")

    for table in TABLES:
        for column in sa.inspect(connection).get_columns(table):
            assert not any(word in column["name"] for word in forbidden), f"{table}.{column['name']}"
    assert "name" not in {c["name"] for c in sa.inspect(connection).get_columns("orders")}


def test_rls_is_enabled_from_its_own_migration(monkeypatch):
    assert_rls_pattern(load_migration(FILE), monkeypatch, TABLES)
