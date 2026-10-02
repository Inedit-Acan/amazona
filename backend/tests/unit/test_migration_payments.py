"""La migración de cobros, reembolsos y eventos (Milestone 44, ADR 0028), ejecutada de verdad.

Lo que solo una migración ejecutada demuestra: que crea lo mismo que declara el modelo y que las garantías de la
base de datos existen **y no impiden guardar evidencia**: un segundo cobro real es un `DUPLICATE_CAPTURE` y uno de
otro importe, un `CAPTURE_MISMATCH`; la restricción de «un `SUCCEEDED` por pedido» protege de *nuestro* código, no
descarta lo que el proveedor cobró.
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

FILE = "a9d2e7b4c136_payments_events_refunds.py"
ORDERS_FILE = "f6a1c8d3e925_orders_and_items.py"
TABLES = ("payments", "refunds", "payment_events")


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


def order(conn, order_id: str = "o-1") -> None:
    row(
        conn,
        "orders",
        id=order_id,
        customer_ref=f"sim_{order_id}",
        market="eu",
        currency="EUR",
        amount_due=50.0,
        status="AWAITING_PAYMENT",
        is_simulated=True,
        correlation_id="c",
        created_at="2026-10-02",
        updated_at="2026-10-02",
    )


def payment(conn, payment_id: str, **overrides) -> None:
    values = {
        "id": payment_id,
        "order_id": "o-1",
        "attempt_number": 1,
        "provider": "simulated-payments",
        "status": "OPEN",
        "amount": 50.0,
        "currency": "EUR",
        "captured_amount": 0,
        "refund_committed_amount": 0,
        "refunded_amount": 0,
        "correlation_id": "c",
        "created_at": "2026-10-02",
        "updated_at": "2026-10-02",
    }
    values.update(overrides)
    row(conn, "payments", **values)


def captured(conn, payment_id: str, attempt: int, **overrides) -> None:
    values = {"attempt_number": attempt, "status": "SUCCEEDED", "captured_amount": 50.0}
    values.update(overrides)
    payment(conn, payment_id, **values)


def seed(conn) -> None:
    order(conn)


# --- La cadena y subir/bajar ---------------------------------------------------------------------------------------


def test_the_revision_chains_after_orders():
    module = load_migration(FILE)

    assert module.revision == "a9d2e7b4c136" and module.down_revision == "f6a1c8d3e925"


def test_upgrade_creates_the_three_tables_and_downgrade_removes_them(connection):
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


# --- Un pedido, varios intentos ------------------------------------------------------------------------------------


def test_an_order_can_have_several_attempts_and_the_number_is_unique(connection):
    migrate(connection)
    seed(connection)

    payment(connection, "p-1", attempt_number=1, status="FAILED")
    payment(connection, "p-2", attempt_number=2, status="EXPIRED")
    payment(connection, "p-3", attempt_number=3, status="OPEN")

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-4", attempt_number=3, status="FAILED")


@pytest.mark.parametrize("status", ["REQUESTED", "OPENING", "UNKNOWN_OUTCOME", "OPEN"])
def test_an_order_has_at_most_one_active_attempt_and_an_unknown_outcome_counts(connection, status):
    migrate(connection)
    seed(connection)
    payment(connection, "p-1", attempt_number=1, status=status)

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-2", attempt_number=2, status="OPEN")


@pytest.mark.parametrize("status", ["FAILED", "EXPIRED"])
def test_a_finished_attempt_does_not_hold_the_slot(connection, status):
    migrate(connection)
    seed(connection)
    payment(connection, "p-1", attempt_number=1, status=status)

    payment(connection, "p-2", attempt_number=2, status="OPEN")  # no falla


def test_different_orders_have_their_own_active_attempt(connection):
    migrate(connection)
    seed(connection)
    order(connection, "o-2")

    payment(connection, "p-1", order_id="o-1")
    payment(connection, "p-2", order_id="o-2")


# --- Un SUCCEEDED por pedido, y la evidencia nunca se descarta -----------------------------------------------------


def test_an_order_has_at_most_one_canonical_succeeded_payment(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    with pytest.raises(sa.exc.IntegrityError):
        captured(connection, "p-2", 2)


def test_a_second_real_capture_can_still_be_stored_as_a_duplicate_capture(connection):
    """El índice protege de nuestro código; no puede impedir guardar que el proveedor cobró dos veces."""
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    captured(connection, "p-2", 2, status="DUPLICATE_CAPTURE", duplicate_of_payment_id="p-1")

    total = connection.execute(sa.text("SELECT sum(captured_amount) FROM payments")).scalar_one()
    assert float(total) == 100.0, "the money that really existed stays auditable"


def test_a_duplicate_capture_must_name_the_payment_it_duplicates_and_only_it(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    with pytest.raises(sa.exc.IntegrityError):
        captured(connection, "p-2", 2, status="DUPLICATE_CAPTURE")  # sin original
    with pytest.raises(sa.exc.IntegrityError):
        captured(connection, "p-3", 3, status="FAILED", captured_amount=0, duplicate_of_payment_id="p-1")


def test_a_capture_of_a_different_amount_is_stored_even_if_it_exceeds_what_was_expected(connection):
    migrate(connection)
    seed(connection)

    captured(connection, "p-1", 1, status="CAPTURE_MISMATCH", captured_amount=80.0)  # más de los 50 esperados
    captured(connection, "p-2", 2, status="CAPTURE_MISMATCH", captured_amount=20.0)  # y menos


def test_a_succeeded_payment_captured_exactly_what_was_expected(connection):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        captured(connection, "p-1", 1, captured_amount=49.0)


@pytest.mark.parametrize("status", ["REQUESTED", "OPENING", "UNKNOWN_OUTCOME", "OPEN", "FAILED", "EXPIRED"])
def test_a_payment_that_is_not_captured_holds_no_captured_money(connection, status):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-1", status=status, captured_amount=10.0)


# --- Los reembolsos nunca superan lo cobrado -----------------------------------------------------------------------


def test_refunds_cannot_exceed_what_was_captured(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("UPDATE payments SET refund_committed_amount = 50.01 WHERE id = 'p-1'"))
    connection.execute(sa.text("UPDATE payments SET refund_committed_amount = 50 WHERE id = 'p-1'"))
    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("UPDATE payments SET refunded_amount = 51 WHERE id = 'p-1'"))


def test_what_was_refunded_cannot_exceed_what_was_set_aside(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("UPDATE payments SET refunded_amount = 10 WHERE id = 'p-1'"))


@pytest.mark.parametrize("column", ["captured_amount", "refund_committed_amount", "refunded_amount"])
def test_no_amount_is_negative(connection, column):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-1", status="CAPTURE_MISMATCH", **{column: -1})


@pytest.mark.parametrize("amount", [0, -3])
def test_a_payment_asks_for_a_positive_amount(connection, amount):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-1", amount=amount)


def test_a_payment_can_only_be_in_a_known_state(connection):
    migrate(connection)
    seed(connection)

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-1", status="PAID")


def test_the_provider_reference_is_unique_per_provider_when_it_exists(connection):
    migrate(connection)
    seed(connection)
    payment(connection, "p-1", attempt_number=1, status="FAILED", provider_payment_ref="simpay_a")

    with pytest.raises(sa.exc.IntegrityError):
        payment(connection, "p-2", attempt_number=2, status="FAILED", provider_payment_ref="simpay_a")
    payment(connection, "p-3", attempt_number=3, status="FAILED", provider_payment_ref=None)
    payment(connection, "p-4", attempt_number=4, status="FAILED", provider_payment_ref=None)


# --- Los eventos ---------------------------------------------------------------------------------------------------


def event(conn, event_id: str, provider_event_id: str, **overrides) -> None:
    values = {
        "id": event_id,
        "provider": "simulated-payments",
        "provider_event_id": provider_event_id,
        "event_type": "payment.succeeded",
        "occurred_at": "2026-10-02 10:00:00",
        "received_at": "2026-10-02 10:00:01",
        "payload_hash": "f" * 64,
        "processing_status": "RECEIVED",
    }
    values.update(overrides)
    row(conn, "payment_events", **values)


def test_the_same_provider_event_cannot_be_stored_twice(connection):
    migrate(connection)
    event(connection, "e-1", "evt_1")

    with pytest.raises(sa.exc.IntegrityError):
        event(connection, "e-2", "evt_1")
    event(connection, "e-3", "evt_2")
    event(connection, "e-4", "evt_1", provider="another-gateway")


@pytest.mark.parametrize("status", ["PENDING", "PROCESSING", "applied"])
def test_an_event_can_only_have_a_known_processing_status(connection, status):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        event(connection, "e-1", "evt_1", processing_status=status)


def test_an_event_amount_always_comes_with_its_currency(connection):
    migrate(connection)

    with pytest.raises(sa.exc.IntegrityError):
        event(connection, "e-1", "evt_1", amount=10.0)
    with pytest.raises(sa.exc.IntegrityError):
        event(connection, "e-2", "evt_2", currency="EUR")
    event(connection, "e-3", "evt_3", amount=10.0, currency="EUR")


def test_an_event_keeps_no_raw_body_column(connection):
    migrate(connection)

    columns = {c["name"] for c in sa.inspect(connection).get_columns("payment_events")}
    assert "payload_hash" in columns
    assert not columns & {"raw_body", "body", "payload", "raw_payload", "headers"}, "the raw body is never stored"


# --- Las devoluciones ----------------------------------------------------------------------------------------------


def refund(conn, refund_id: str, **overrides) -> None:
    values = {
        "id": refund_id,
        "payment_id": "p-1",
        "provider": "simulated-payments",
        "origin": "OPERATOR",
        "status": "REQUESTED",
        "amount": 5.0,
        "currency": "EUR",
        "reason": "requested_by_customer",
        "correlation_id": "c",
        "requested_at": "2026-10-02",
        "created_at": "2026-10-02",
        "updated_at": "2026-10-02",
    }
    values.update(overrides)
    row(conn, "refunds", **values)


def test_a_refund_has_a_known_origin_state_and_a_positive_amount(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)

    refund(connection, "r-1")
    refund(connection, "r-2", origin="PROVIDER", status="SUCCEEDED")
    for bad in ({"origin": "ROBOT"}, {"status": "PENDING"}, {"amount": 0}, {"amount": -1}):
        with pytest.raises(sa.exc.IntegrityError):
            refund(connection, "r-bad", **bad)


def test_a_provider_refund_reference_is_unique_when_it_exists(connection):
    migrate(connection)
    seed(connection)
    captured(connection, "p-1", 1)
    refund(connection, "r-1", provider_refund_ref="simref_a")

    with pytest.raises(sa.exc.IntegrityError):
        refund(connection, "r-2", provider_refund_ref="simref_a")
    refund(connection, "r-3")
    refund(connection, "r-4")


def test_the_migration_does_not_touch_other_tables(connection):
    connection.execute(sa.text("CREATE TABLE bystander (id INTEGER PRIMARY KEY, note TEXT)"))
    connection.execute(sa.text("INSERT INTO bystander (id, note) VALUES (1, 'unchanged')"))

    migrate(connection)
    migrate(connection, "downgrade")

    assert connection.execute(sa.text("SELECT note FROM bystander")).scalar_one() == "unchanged"


def test_rls_is_enabled_from_its_own_migration(monkeypatch):
    assert_rls_pattern(load_migration(FILE), monkeypatch, TABLES)
