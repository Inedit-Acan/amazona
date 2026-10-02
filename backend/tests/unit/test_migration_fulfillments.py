"""La migración de fulfillments (Milestone 44, ADR 0028 §6), ejecutada de verdad.

Lo que solo una migración ejecutada demuestra: que crea lo mismo que declara el modelo y que las garantías de la base
de datos existen. La que importa: **un fulfillment con compra jamás termina `CANCELLED` ni `FAILED`**, es decir, una
unidad comprada no vuelve al pool y no se puede comprar dos veces. Y que el esquema **no impide** varios fulfillments
por pedido ni repartir una misma línea entre varios.
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

FILE = "b3c8f1a5d742_fulfillments.py"
ORDERS_FILE = "f6a1c8d3e925_orders_and_items.py"
TABLES = ("fulfillments", "fulfillment_items")
NOW = "2026-10-02"


@pytest.fixture()
def connection():
    engine = new_connection()
    with engine.connect() as conn:
        apply_prerequisites(conn, "products", "suppliers", "supplier_quotes")
        run(conn, load_migration(ORDERS_FILE), "upgrade")
        yield conn
    engine.dispose()


def migrate(conn, direction: str = "upgrade") -> None:
    run(conn, load_migration(FILE), direction)


def row(conn, table: str, **values) -> None:
    conn.execute(
        sa.text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"), values
    )


def seed(conn) -> None:
    row(
        conn,
        "products",
        id="prod-1",
        name="Widget",
        category="home",
        status="ACTIVE",
        created_by="t",
        source="manual",
        created_at=NOW,
        updated_at=NOW,
    )
    row(
        conn,
        "orders",
        id="o-1",
        customer_ref="sim_o-1",
        market="eu",
        currency="EUR",
        amount_due=50.0,
        status="PAID",
        is_simulated=True,
        correlation_id="c",
        created_at=NOW,
        updated_at=NOW,
    )
    for number in (1, 2):
        row(
            conn,
            "order_items",
            id=f"i-{number}",
            order_id="o-1",
            line_number=number,
            product_id="prod-1",
            quantity=4,
            allocated_quantity=0,
            unit_price=12.5,
            line_total=50.0,
            created_at=NOW,
            updated_at=NOW,
        )


def fulfillment(conn, fulfillment_id: str, **overrides) -> None:
    values = {
        "id": fulfillment_id,
        "order_id": "o-1",
        "provider": "simulated-fulfilment",
        "status": "READY",
        "failed_attempts": 0,
        "created_by": "t",
        "correlation_id": "c",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    row(conn, "fulfillments", **values)


def item(conn, item_id: str, fulfillment_id: str, order_item_id: str, quantity: int = 1) -> None:
    row(
        conn,
        "fulfillment_items",
        id=item_id,
        fulfillment_id=fulfillment_id,
        order_item_id=order_item_id,
        quantity=quantity,
        created_at=NOW,
        updated_at=NOW,
    )


def ready(conn):
    migrate(conn)
    seed(conn)


# --- La cadena y subir/bajar ---------------------------------------------------------------------------------------


def test_the_revision_chains_after_the_payments():
    module = load_migration(FILE)

    assert module.revision == "b3c8f1a5d742" and module.down_revision == "a9d2e7b4c136"


def test_upgrade_creates_the_two_tables_and_downgrade_removes_them(connection):
    migrate(connection)
    assert set(TABLES) <= set(sa.inspect(connection).get_table_names())

    migrate(connection, "downgrade")

    assert not set(TABLES) & set(sa.inspect(connection).get_table_names())
    assert "orders" in sa.inspect(connection).get_table_names(), "the downgrade leaves the orders alone"


def test_it_can_be_applied_again_after_a_downgrade(connection):
    migrate(connection)
    migrate(connection, "downgrade")

    migrate(connection)

    assert set(TABLES) <= set(sa.inspect(connection).get_table_names())


def test_the_migration_creates_what_the_model_declares(connection):
    migrate(connection)

    assert_migration_matches_model(connection, TABLES)


# --- Un pedido, varios fulfillments ---------------------------------------------------------------------------------


def test_an_order_can_have_several_fulfillments_and_a_line_can_be_split_among_them(connection):
    ready(connection)

    fulfillment(connection, "f-1")
    fulfillment(connection, "f-2")
    item(connection, "fi-1", "f-1", "i-1", 2)
    item(connection, "fi-2", "f-2", "i-1", 2)  # la misma línea, repartida
    item(connection, "fi-3", "f-2", "i-2", 4)

    assert connection.execute(sa.text("SELECT count(*) FROM fulfillments WHERE order_id = 'o-1'")).scalar_one() == 2


def test_a_fulfillment_covers_a_line_only_once(connection):
    ready(connection)
    fulfillment(connection, "f-1")
    item(connection, "fi-1", "f-1", "i-1")

    with pytest.raises(sa.exc.IntegrityError):
        item(connection, "fi-2", "f-1", "i-1")


@pytest.mark.parametrize("quantity", [0, -1])
def test_a_fulfillment_line_needs_a_positive_quantity(connection, quantity):
    ready(connection)
    fulfillment(connection, "f-1")

    with pytest.raises(sa.exc.IntegrityError):
        item(connection, "fi-1", "f-1", "i-1", quantity)


def test_a_fulfillment_belongs_to_an_order_that_exists(connection):
    migrate(connection)
    connection.execute(sa.text("PRAGMA foreign_keys = ON"))

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", order_id="nope")


# --- Estados ------------------------------------------------------------------------------------------------------


def test_a_fulfillment_can_only_be_in_a_known_state(connection):
    ready(connection)

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", status="DELIVERED")


@pytest.mark.parametrize("status", ["READY", "PURCHASING", "FAILED", "CANCELLED"])
def test_a_fulfillment_that_never_bought_has_no_purchase_date_requirement(connection, status):
    ready(connection)

    fulfillment(connection, "f-1", status=status)


@pytest.mark.parametrize("status", ["PURCHASED", "SHIPPING", "SHIPPED", "COMPLETED"])
def test_a_bought_fulfillment_has_its_purchase_date(connection, status):
    ready(connection)
    extra = {"shipped_at": NOW, "completed_at": NOW, "completed_by": "owner"}

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", status=status, **extra)
    fulfillment(connection, "f-2", status=status, purchased_at=NOW, **extra)


@pytest.mark.parametrize("status", ["SHIPPED", "COMPLETED"])
def test_a_sent_fulfillment_has_its_shipping_date(connection, status):
    ready(connection)

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", status=status, purchased_at=NOW, completed_at=NOW, completed_by="owner")


def test_a_delivered_fulfillment_names_who_confirmed_it(connection):
    ready(connection)
    sent = {"status": "COMPLETED", "purchased_at": NOW, "shipped_at": NOW, "completed_at": NOW}

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", **sent)
    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-2", completed_by=None, **sent)
    fulfillment(connection, "f-3", completed_by="owner@amazona.local", **sent)


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_a_fulfillment_with_a_purchase_never_ends_failed_or_cancelled(connection, status):
    """El respaldo en la base de datos de «una unidad comprada no vuelve al pool»: ni siquiera un `UPDATE` directo
    puede cerrar como cancelado o fallido algo que se compró."""
    ready(connection)

    with pytest.raises(sa.exc.IntegrityError, match="a_purchased_unit_never_returns_to_the_pool"):
        fulfillment(connection, "f-1", status=status, purchased_at=NOW)
    fulfillment(connection, "f-2")
    connection.execute(sa.text("UPDATE fulfillments SET purchased_at = :t WHERE id = 'f-2'"), {"t": NOW})
    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text(f"UPDATE fulfillments SET status = '{status}' WHERE id = 'f-2'"))


@pytest.mark.parametrize("phase", ["purchase", "ship"])
def test_an_unknown_outcome_names_its_phase(connection, phase):
    ready(connection)

    fulfillment(
        connection, "f-1", status="UNKNOWN_OUTCOME", unknown_phase=phase, purchased_at=NOW if phase == "ship" else None
    )


def test_an_unknown_outcome_without_a_phase_is_refused_and_a_phase_without_it_too(connection):
    ready(connection)

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", status="UNKNOWN_OUTCOME")
    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-2", status="READY", unknown_phase="purchase")
    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-3", status="UNKNOWN_OUTCOME", unknown_phase="teleport")


def test_failed_attempts_cannot_be_negative(connection):
    ready(connection)

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-1", failed_attempts=-1)


def test_the_purchase_reference_is_unique_per_provider_when_it_exists(connection):
    ready(connection)
    fulfillment(connection, "f-1", purchase_reference="simpo_a")

    with pytest.raises(sa.exc.IntegrityError):
        fulfillment(connection, "f-2", purchase_reference="simpo_a")
    fulfillment(connection, "f-3", purchase_reference="simpo_a", provider="another-provider")
    fulfillment(connection, "f-4")
    fulfillment(connection, "f-5")  # sin referencia: tantos como se quiera


def test_a_fulfillment_keeps_no_personal_data_columns(connection):
    migrate(connection)
    names = {c["name"] for c in sa.inspect(connection).get_columns("fulfillments")} | {
        c["name"] for c in sa.inspect(connection).get_columns("fulfillment_items")
    }

    forbidden = {"name", "email", "phone", "address", "recipient", "street", "city", "postcode", "tax_id"}
    assert not names & forbidden, sorted(names & forbidden)


def test_the_migration_does_not_touch_other_tables(connection):
    connection.execute(sa.text("CREATE TABLE bystander (id INTEGER PRIMARY KEY, note TEXT)"))
    connection.execute(sa.text("INSERT INTO bystander (id, note) VALUES (1, 'unchanged')"))

    migrate(connection)
    migrate(connection, "downgrade")

    assert connection.execute(sa.text("SELECT note FROM bystander")).scalar_one() == "unchanged"


def test_rls_is_enabled_from_its_own_migration(monkeypatch):
    assert_rls_pattern(load_migration(FILE), monkeypatch, TABLES)
