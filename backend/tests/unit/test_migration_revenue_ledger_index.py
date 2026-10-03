"""La migración del índice de las lecturas del registro de ingresos (Milestone 45, ADR 0030), ejecutada de verdad.

Es aditiva: solo añade un índice `(occurred_at, id)` (con `INCLUDE` en PostgreSQL). Lo que se afirma: que lo crea y
lo quita, que no toca ni una fila ni la tabla, que el resultado es lo que declara el modelo y que se puede bajar y
volver a subir. La versión PostgreSQL (el `INCLUDE` y el plan) está en
`tests/integration/test_revenue_ledger_index_postgres.py`.
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

LEDGER_FILE = "c4e8b1d9a273_revenue_ledger_entries.py"
FILE = "e5a1d7c93b04_revenue_ledger_occurred_at_index.py"
ORDERS_FILE = "f6a1c8d3e925_orders_and_items.py"
PAYMENTS_FILE = "a9d2e7b4c136_payments_events_refunds.py"
TABLE = "revenue_ledger_entries"
INDEX = "ix_revenue_entries_occurred_at"


@pytest.fixture()
def connection():
    engine = new_connection()
    with engine.connect() as conn:
        apply_prerequisites(conn, "products", "suppliers", "supplier_quotes")
        run(conn, load_migration(ORDERS_FILE), "upgrade")
        run(conn, load_migration(PAYMENTS_FILE), "upgrade")
        run(conn, load_migration(LEDGER_FILE), "upgrade")
        yield conn
    engine.dispose()


def migrate(conn, direction: str = "upgrade") -> None:
    run(conn, load_migration(FILE), direction)


def indexes(conn) -> dict[str, list[str]]:
    return {i["name"]: list(i["column_names"]) for i in sa.inspect(conn).get_indexes(TABLE)}


def insert_entry(conn) -> None:
    conn.execute(
        sa.text(
            f"INSERT INTO {TABLE} (id, kind, classification, payment_event_id, payment_id, order_id, amount, currency, "
            "occurred_at, recorded_at) VALUES ('e1', 'CAPTURE', 'ORDER_PAYMENT', 'ev1', 'p1', 'o1', 50, 'EUR', "
            "'2026-10-03 10:00:00', '2026-10-03 10:00:01')"
        )
    )


def test_the_revision_chains_after_the_ledger_and_is_the_head():
    module = load_migration(FILE)

    assert module.revision == "e5a1d7c93b04" and module.down_revision == "c4e8b1d9a273"


def test_upgrade_adds_the_index_on_occurred_at_and_id_and_downgrade_removes_only_it(connection):
    assert INDEX not in indexes(connection)

    migrate(connection)
    assert indexes(connection)[INDEX] == ["occurred_at", "id"]
    migrate(connection, "downgrade")

    assert INDEX not in indexes(connection)
    assert TABLE in sa.inspect(connection).get_table_names(), "the downgrade leaves the table and its entries"


def test_it_touches_no_row_and_no_other_index(connection):
    insert_entry(connection)
    before = connection.execute(sa.text(f"SELECT * FROM {TABLE}")).all()
    others = {name for name in indexes(connection)}

    migrate(connection)

    assert connection.execute(sa.text(f"SELECT * FROM {TABLE}")).all() == before
    assert set(indexes(connection)) == others | {INDEX}
    migrate(connection, "downgrade")
    assert connection.execute(sa.text(f"SELECT * FROM {TABLE}")).all() == before
    assert set(indexes(connection)) == others


def test_it_can_be_applied_again_after_a_downgrade(connection):
    migrate(connection)
    migrate(connection, "downgrade")

    migrate(connection)

    assert indexes(connection)[INDEX] == ["occurred_at", "id"]


def test_the_migrated_table_is_what_the_model_declares(connection):
    migrate(connection)

    assert_migration_matches_model(connection, (TABLE,))


def test_the_append_only_triggers_survive_the_index(connection):
    migrate(connection)
    insert_entry(connection)

    with pytest.raises(sa.exc.IntegrityError, match="append-only"):
        connection.execute(sa.text(f"UPDATE {TABLE} SET amount = 1"))
