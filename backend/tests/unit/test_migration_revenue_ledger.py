"""La migración del registro de ingresos verificados (Milestone 45, ADR 0030), ejecutada de verdad sobre SQLite.

Lo que solo una migración ejecutada demuestra: que crea **lo mismo que declara el modelo** (las pruebas usan
`create_all`; si no, hablarían de tablas distintas que la base real), que el trigger append-only existe y rechaza, que
las restricciones de identidad y de forma están, que **no retrorrellena** nada, que se puede bajar y volver a subir sin
tocar un solo hecho de pago, y que activa RLS desde su propia migración. La versión PostgreSQL (función, triggers,
`TRUNCATE`) está en `tests/integration/test_revenue_ledger_migration_postgres.py`.
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

from app.db.models import revenue as model

FILE = "c4e8b1d9a273_revenue_ledger_entries.py"
ORDERS_FILE = "f6a1c8d3e925_orders_and_items.py"
PAYMENTS_FILE = "a9d2e7b4c136_payments_events_refunds.py"
TABLE = "revenue_ledger_entries"
TRIGGERS = {"revenue_ledger_entries_no_update", "revenue_ledger_entries_no_delete"}
COLUMNS = (
    "id, kind, classification, payment_event_id, payment_id, order_id, refund_id, capture_entry_id, amount, currency, "
    "occurred_at, recorded_at"
)


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


def triggers(conn) -> set[str]:
    rows = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).all()
    return {r[0] for r in rows if r[0].startswith("revenue_ledger_entries")}


def insert(conn, **override) -> None:
    row = {
        "id": "e1",
        "kind": "CAPTURE",
        "classification": "ORDER_PAYMENT",
        "payment_event_id": "ev1",
        "payment_id": "p1",
        "order_id": "o1",
        "refund_id": None,
        "capture_entry_id": None,
        "amount": "50.0000",
        "currency": "EUR",
        "occurred_at": "2026-10-03 10:00:00",
        "recorded_at": "2026-10-03 10:00:01",
    }
    row.update(override)
    conn.execute(
        sa.text(f"INSERT INTO {TABLE} ({COLUMNS}) VALUES (:id, :kind, :classification, :payment_event_id, :payment_id, "
                ":order_id, :refund_id, :capture_entry_id, :amount, :currency, :occurred_at, :recorded_at)"),
        row,
    )  # fmt: skip


def stored_event(conn, event_id: str = "ev0") -> None:
    conn.execute(
        sa.text(
            "INSERT INTO payment_events (id, provider, provider_event_id, event_type, occurred_at, received_at, "
            "payload_hash, processing_status) VALUES (:id, 'simulated-payments', :pid, 'payment.succeeded', "
            "'2026-10-03 10:00:00', '2026-10-03 10:00:01', 'h', 'APPLIED')"
        ),
        {"id": event_id, "pid": f"evt-{event_id}"},
    )


def test_the_revision_chains_after_the_payment_event_reconcile_fields():
    module = load_migration(FILE)

    assert module.revision == "c4e8b1d9a273" and module.down_revision == "d7e2a9c4f1b8"


def test_upgrade_creates_the_table_and_the_append_only_triggers_and_downgrade_removes_them(connection):
    assert TABLE not in sa.inspect(connection).get_table_names()

    migrate(connection)
    assert TABLE in sa.inspect(connection).get_table_names() and triggers(connection) == TRIGGERS
    migrate(connection, "downgrade")

    assert TABLE not in sa.inspect(connection).get_table_names() and triggers(connection) == set()
    names = sa.inspect(connection).get_table_names()
    assert {"payments", "refunds", "payment_events"} <= set(names), "the facts stay: the ledger is a projection"


def test_it_can_be_applied_again_after_a_downgrade(connection):
    migrate(connection)
    migrate(connection, "downgrade")

    migrate(connection)

    assert TABLE in sa.inspect(connection).get_table_names() and triggers(connection) == TRIGGERS


def test_the_migrated_table_is_what_the_model_declares(connection):
    migrate(connection)

    assert_migration_matches_model(connection, (TABLE,))
    foreign_keys = sa.inspect(connection).get_foreign_keys(TABLE)
    inherited = ["capture_entry_id", "classification", "currency", "payment_id"]
    inheritance = [
        fk for fk in foreign_keys if fk["referred_table"] == TABLE and fk["constrained_columns"] == inherited
    ]
    assert len(inheritance) == 1, "a refund inherits classification, currency and payment from its capture"
    assert {fk["referred_table"] for fk in foreign_keys} == {TABLE, "payment_events", "payments", "orders", "refunds"}


def test_the_trigger_text_of_the_migration_and_of_the_model_is_the_same():
    module = load_migration(FILE)

    assert module.APPEND_ONLY_POSTGRESQL == model.APPEND_ONLY_POSTGRESQL
    assert module.APPEND_ONLY_SQLITE == model.APPEND_ONLY_SQLITE


def test_it_does_not_backfill_and_does_not_touch_the_facts_that_already_exist(connection):
    stored_event(connection)
    before = connection.execute(sa.text("SELECT * FROM payment_events")).all()

    migrate(connection)

    assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar() == 0
    assert connection.execute(sa.text("SELECT * FROM payment_events")).all() == before


def test_downgrade_keeps_the_payment_facts_untouched(connection):
    migrate(connection)
    stored_event(connection)
    before = connection.execute(sa.text("SELECT * FROM payment_events")).all()

    migrate(connection, "downgrade")

    assert connection.execute(sa.text("SELECT * FROM payment_events")).all() == before


def test_an_entry_cannot_be_updated_or_deleted(connection):
    migrate(connection)
    insert(connection)

    with pytest.raises(sa.exc.IntegrityError, match="append-only - UPDATE"):
        connection.execute(sa.text(f"UPDATE {TABLE} SET amount = 1"))
    with pytest.raises(sa.exc.IntegrityError, match="append-only - DELETE"):
        connection.execute(sa.text(f"DELETE FROM {TABLE}"))

    assert connection.execute(sa.text(f"SELECT amount FROM {TABLE}")).scalar() == 50


@pytest.mark.parametrize(
    "override, message",
    [
        ({"id": "e2", "payment_id": "p2"}, "payment_event_id"),  # el mismo evento dos veces
        ({"id": "e2", "payment_event_id": "ev2"}, "payment_id"),  # una CAPTURE por cobro
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "amount": 0}, "amount_positive"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "amount": -5}, "amount_positive"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "classification": "BOGUS"}, "classification"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "kind": "REVERSAL"}, "ck_revenue_entries_kind"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "currency": "EU"}, "currency_shape"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "refund_id": "r1"}, "refund_names"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "kind": "REFUND"}, "refund_names"),
        ({"id": "e2", "payment_event_id": "ev2", "payment_id": "p2", "capture_entry_id": "e1"}, "refund_names"),
    ],
)
def test_the_database_refuses_repeated_or_malformed_entries(connection, override, message):
    migrate(connection)
    insert(connection)

    with pytest.raises(sa.exc.IntegrityError, match=message):
        insert(connection, **override)


def test_one_entry_per_refund_and_a_refund_names_its_capture(connection):
    migrate(connection)
    insert(connection)
    refund = {"id": "e2", "kind": "REFUND", "payment_event_id": "ev2", "refund_id": "r1", "capture_entry_id": "e1"}
    insert(connection, **refund)

    with pytest.raises(sa.exc.IntegrityError, match="refund_id"):
        insert(connection, **{**refund, "id": "e3", "payment_event_id": "ev3"})
    assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar() == 2


def test_rls_is_enabled_from_its_own_migration(monkeypatch):
    assert_rls_pattern(load_migration(FILE), monkeypatch, (TABLE,))


def test_postgresql_gets_the_function_and_the_triggers_and_loses_them_on_the_way_down(monkeypatch):
    from m44_migration_test_support import RecordingOp

    module = load_migration(FILE)
    up = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", up)
    module.upgrade()
    assert any("CREATE OR REPLACE FUNCTION revenue_ledger_entries_append_only()" in s for s in up.statements)
    assert any("BEFORE UPDATE OR DELETE ON revenue_ledger_entries" in s for s in up.statements)
    assert any("BEFORE TRUNCATE ON revenue_ledger_entries" in s for s in up.statements)

    down = RecordingOp(supabase_roles=False)
    monkeypatch.setattr(module, "op", down)
    module.downgrade()
    assert "DROP FUNCTION IF EXISTS revenue_ledger_entries_append_only()" in down.statements
