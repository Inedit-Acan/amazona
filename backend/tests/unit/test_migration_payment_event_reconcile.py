"""La migración de los campos de proceso de `payment_events` (Milestone 45, ADR 0029 §6), ejecutada de verdad.

Lo que solo una migración ejecutada demuestra: que añade lo que declara el modelo, que **no toca los eventos que ya
existen** (cuentan 0
intentos y siguen `RECEIVED`), que `CHECK reconcile_attempts >= 0` existe, y que se puede bajar y volver a subir sin
perder el hecho
financiero (la bajada solo quita metadatos de proceso).
"""

import pytest
import sqlalchemy as sa
from m44_migration_test_support import (
    apply_prerequisites,
    assert_migration_matches_model,
    load_migration,
    new_connection,
    run,
)

FILE = "d7e2a9c4f1b8_payment_event_reconcile_fields.py"
ORDERS_FILE = "f6a1c8d3e925_orders_and_items.py"
PAYMENTS_FILE = "a9d2e7b4c136_payments_events_refunds.py"
FIELDS = {"reconcile_attempts", "last_reconcile_error", "last_reconcile_at"}


@pytest.fixture()
def connection():
    engine = new_connection()
    with engine.connect() as conn:
        apply_prerequisites(conn, "products", "suppliers", "supplier_quotes")
        run(conn, load_migration(ORDERS_FILE), "upgrade")
        run(conn, load_migration(PAYMENTS_FILE), "upgrade")
        yield conn
    engine.dispose()


def migrate(conn, direction: str = "upgrade") -> None:
    run(conn, load_migration(FILE), direction)


def columns(conn) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns("payment_events")}


def stored_event(conn, event_id: str = "e-1") -> None:
    conn.execute(
        sa.text(
            "INSERT INTO payment_events (id, provider, provider_event_id, event_type, occurred_at, received_at, "
            "payload_hash, "
            "processing_status) VALUES (:id, 'simulated-payments', :pid, 'payment.succeeded', '2026-10-03 10:00:00', "
            "'2026-10-03 10:00:01', 'h', 'RECEIVED')"
        ),
        {"id": event_id, "pid": f"evt-{event_id}"},
    )


def test_the_revision_chains_after_fulfillments_and_is_the_head_of_this_chain():
    module = load_migration(FILE)

    assert module.revision == "d7e2a9c4f1b8" and module.down_revision == "b3c8f1a5d742"


def test_upgrade_adds_the_three_process_fields_and_downgrade_removes_them(connection):
    assert not FIELDS & columns(connection)

    migrate(connection)
    assert FIELDS <= columns(connection)
    migrate(connection, "downgrade")

    assert not FIELDS & columns(connection)
    assert "payment_events" in sa.inspect(connection).get_table_names(), "the downgrade leaves the table and its facts"


def test_it_can_be_applied_again_after_a_downgrade(connection):
    migrate(connection)
    migrate(connection, "downgrade")

    migrate(connection)

    assert FIELDS <= columns(connection)


def test_the_migrated_table_is_what_the_model_declares(connection):
    migrate(connection)

    assert_migration_matches_model(connection, ("payment_events",))


def test_an_existing_event_keeps_everything_and_counts_zero_attempts(connection):
    stored_event(connection)

    migrate(connection)

    row = connection.execute(
        sa.text(
            "SELECT processing_status, provider_event_id, payload_hash, reconcile_attempts, last_reconcile_error, "
            "last_reconcile_at FROM payment_events"
        )
    ).one()
    assert tuple(row) == ("RECEIVED", "evt-e-1", "h", 0, None, None)


def test_downgrade_keeps_the_events_untouched(connection):
    migrate(connection)
    stored_event(connection)

    migrate(connection, "downgrade")

    query = sa.text("SELECT processing_status, provider_event_id, payload_hash FROM payment_events")
    row = connection.execute(query).one()
    assert tuple(row) == ("RECEIVED", "evt-e-1", "h")


def test_a_negative_attempt_count_is_refused_by_the_database(connection):
    migrate(connection)
    stored_event(connection)

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("UPDATE payment_events SET reconcile_attempts = -1"))


def test_the_attempt_count_cannot_be_null(connection):
    migrate(connection)
    stored_event(connection)

    with pytest.raises(sa.exc.IntegrityError):
        connection.execute(sa.text("UPDATE payment_events SET reconcile_attempts = NULL"))
