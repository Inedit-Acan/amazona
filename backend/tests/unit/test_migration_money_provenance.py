"""La migración 44.ª sobre SQLite: el origen del dinero como propiedad persistida (Milestone 46, ADR 0031 §7 y §8).

Lo que SQLite puede demostrar. Lo propio de PostgreSQL (la función, `TRUNCATE`, la RLS de verdad, la transacción) está
en
`tests/integration/test_money_provenance_migration_postgres.py`.

**La trampa que esta prueba vigila.** En SQLite, quitar un `DEFAULT` o añadir una restricción obliga a recrear la tabla
(`batch_alter_table`), y recrear la tabla **destruye sus disparadores** sin ningún error: el registro de ingresos
dejaba de
ser *append-only*. Una migración que solo conserve los índices parece correcta y no lo es. Por eso aquí se comprueba,
tras subir,
bajar y volver a subir, que los disparadores **existen y se comportan**.
"""

import pytest
import sqlalchemy as sa
from m44_migration_test_support import (
    RecordingOp,
    apply_prerequisites,
    assert_migration_matches_model,
    load_migration,
    new_connection,
    run,
)
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.db.models import payment as payment_model
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.registry import IMPLEMENTATIONS, ProviderNotAvailableError, ProviderRegistry

FILE = "b7e4a1c9d052_money_provenance.py"
CHAIN = (
    "f6a1c8d3e925_orders_and_items.py",
    "a9d2e7b4c136_payments_events_refunds.py",
    "d7e2a9c4f1b8_payment_event_reconcile_fields.py",
    "c4e8b1d9a273_revenue_ledger_entries.py",
    "e5a1d7c93b04_revenue_ledger_occurred_at_index.py",
)
TABLES = ("payments", "payment_events", "revenue_ledger_entries")
LEDGER = "revenue_ledger_entries"
APPEND_ONLY = {"revenue_ledger_entries_no_update", "revenue_ledger_entries_no_delete"}
IMMUTABLE = {"payments_provider_kind_immutable", "payment_events_provider_kind_immutable"}
NEW_CONSTRAINT_NAMES = {
    "ck_payments_provider_kind",
    "ck_payment_events_provider_kind",
    "ck_revenue_entries_provider_kind",
    "uq_payments_id_provider_kind",
    "uq_payment_events_id_provider_kind",
}
NEW_FOREIGN_KEYS = {
    "fk_payment_events_payment_kind": ("payment_events", ["payment_id", "provider_kind"], "payments"),
    "fk_revenue_entries_payment_kind": (LEDGER, ["payment_id", "provider_kind"], "payments"),
    "fk_revenue_entries_event_kind": (LEDGER, ["payment_event_id", "provider_kind"], "payment_events"),
}


def migration():
    return load_migration(FILE)


def stored_payment(conn, payment_id: str, *, provider: str = "simulated-payments", ref: str | None = None, **extra):
    values = {
        "id": payment_id,
        "order_id": "o" + payment_id.removeprefix("p"),  # un cobro `SUCCEEDED` por pedido (índice parcial)
        "attempt_number": 1,
        "provider": provider,
        "provider_payment_ref": ref,
        "status": "SUCCEEDED",
        "amount": "50.0000",
        "currency": "EUR",
        "captured_amount": "50.0000",
        "refund_committed_amount": "0",
        "refunded_amount": "0",
        "correlation_id": "c",
        "created_at": "2026-10-03 10:00:00",
        "updated_at": "2026-10-03 10:00:00",
    }
    values.update(extra)
    columns = ", ".join(values)
    conn.execute(sa.text(f"INSERT INTO payments ({columns}) VALUES ({', '.join(':' + k for k in values)})"), values)


def stored_event(conn, event_id: str, *, payment_id: str | None, provider: str = "simulated-payments", **extra):
    values = {
        "id": event_id,
        "provider": provider,
        "provider_event_id": f"evt-{event_id}",
        "event_type": "payment.succeeded",
        "payment_id": payment_id,
        "occurred_at": "2026-10-03 10:00:00",
        "received_at": "2026-10-03 10:00:01",
        "payload_hash": "h",
        "processing_status": "APPLIED" if payment_id else "UNMATCHED",
    }
    values.update(extra)
    columns = ", ".join(values)
    conn.execute(
        sa.text(f"INSERT INTO payment_events ({columns}) VALUES ({', '.join(':' + k for k in values)})"), values
    )


def stored_entry(conn, entry_id: str, *, event_id: str, payment_id: str, **extra):
    values = {
        "id": entry_id,
        "kind": "CAPTURE",
        "classification": "ORDER_PAYMENT",
        "payment_event_id": event_id,
        "payment_id": payment_id,
        "order_id": "o" + payment_id.removeprefix("p"),
        "refund_id": None,
        "capture_entry_id": None,
        "amount": "50.0000",
        "currency": "EUR",
        "occurred_at": "2026-10-03 10:00:00",
        "recorded_at": "2026-10-03 10:00:01",
    }
    values.update(extra)
    columns = ", ".join(values)
    conn.execute(sa.text(f"INSERT INTO {LEDGER} ({columns}) VALUES ({', '.join(':' + k for k in values)})"), values)


@pytest.fixture()
def before():
    """La cadena hasta la última migración **anterior** a la 44.ª, con hechos históricos: dos cobros, tres eventos (uno
    `UNMATCHED`, sin cobro) y dos entradas del registro."""
    engine = new_connection()
    with engine.connect() as conn:
        apply_prerequisites(conn, "products", "suppliers", "supplier_quotes")
        for name in CHAIN:
            run(conn, load_migration(name), "upgrade")
        stored_payment(conn, "p1", ref="simpay_1")
        stored_payment(conn, "p2", ref="simpay_2")
        stored_event(conn, "ev1", payment_id="p1")
        stored_event(conn, "ev2", payment_id="p2")
        stored_event(conn, "ev3", payment_id=None)
        stored_entry(conn, "l1", event_id="ev1", payment_id="p1")
        stored_entry(conn, "l2", event_id="ev2", payment_id="p2")
        conn.commit()
        yield conn
    engine.dispose()


def up(conn) -> None:
    run(conn, migration(), "upgrade")
    conn.commit()


def down(conn) -> None:
    run(conn, migration(), "downgrade")
    conn.commit()


def columns(conn, table: str) -> dict[str, tuple]:
    """nombre → (no nulo, valor por defecto)."""
    return {row[1]: (bool(row[3]), row[4]) for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def triggers(conn) -> set[str]:
    return {name for (name,) in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))}


def index_sql(conn) -> dict[str, str]:
    rows = conn.execute(sa.text("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"))
    return {name: " ".join(sql.split()) for name, sql in rows}


def kinds(conn, table: str) -> dict[str, str]:
    return {row[0]: row[1] for row in conn.execute(sa.text(f"SELECT id, provider_kind FROM {table}"))}


def fk_names(conn, table: str) -> set[str]:
    return {fk["name"] for fk in sa.inspect(conn).get_foreign_keys(table) if fk["name"]}


# --- La cadena y la premisa del relleno -------------------------------------------------------------------------------


def test_the_revision_chains_after_the_revenue_ledger_index():
    module = migration()

    assert module.revision == "b7e4a1c9d052" and module.down_revision == "e5a1d7c93b04"


def test_the_backfill_premise_only_the_simulator_can_have_opened_a_payment():
    """El relleno `mock` es verdad y no una suposición porque el registro de pagos solo admite `MOCK`. Si algún día se
    añade un adaptador no simulado, esta prueba falla y obliga a revisar el relleno antes de seguir."""
    assert set(IMPLEMENTATIONS[IntegrationDomain.PAYMENTS]) == {ProviderKind.MOCK}

    for kind in (ProviderKind.SANDBOX, ProviderKind.REAL, ProviderKind.COMPOSITE):
        registry = ProviderRegistry(Settings(payments_provider=kind))
        with pytest.raises(ProviderNotAvailableError):
            registry.resolve(IntegrationDomain.PAYMENTS)


# --- Subir, bajar, subir, con hechos históricos
# ------------------------------------------------------------------------


def test_upgrade_backfills_the_history_as_mock_and_keeps_every_fact(before):
    up(before)

    assert kinds(before, "payments") == {"p1": "mock", "p2": "mock"}
    assert kinds(before, "payment_events") == {"ev1": "mock", "ev2": "mock", "ev3": "mock"}
    assert kinds(before, LEDGER) == {"l1": "mock", "l2": "mock"}
    amounts = before.execute(sa.text(f"SELECT id, amount FROM {LEDGER} ORDER BY id")).all()
    assert [(i, float(a)) for i, a in amounts] == [("l1", 50.0), ("l2", 50.0)]  # SQLite guarda los números como números


def test_upgrade_downgrade_upgrade_with_data(before):
    up(before)
    down(before)

    for table in TABLES:
        assert "provider_kind" not in columns(before, table), table
    assert before.execute(sa.text("SELECT count(*) FROM payments")).scalar() == 2
    assert before.execute(sa.text(f"SELECT count(*) FROM {LEDGER}")).scalar() == 2

    up(before)

    assert kinds(before, "payments") == {"p1": "mock", "p2": "mock"}
    assert kinds(before, "payment_events")["ev3"] == "mock"
    assert kinds(before, LEDGER) == {"l1": "mock", "l2": "mock"}


# --- El esquema final
# ---------------------------------------------------------------------------------------------------


def test_the_final_schema_has_no_default_and_the_column_is_not_null(before):
    up(before)

    for table in TABLES:
        not_null, default = columns(before, table)["provider_kind"]
        assert not_null, f"{table}.provider_kind must be NOT NULL"
        assert default is None, f"{table}.provider_kind must have no DEFAULT: a new operation declares its origin"


def test_an_insert_without_an_origin_is_refused(before):
    up(before)

    with pytest.raises(DBAPIError, match="NOT NULL"):
        stored_payment(before, "p9", ref="simpay_9")  # sin provider_kind
    before.rollback()
    with pytest.raises(DBAPIError, match="NOT NULL"):
        stored_event(before, "ev9", payment_id=None)
    before.rollback()
    with pytest.raises(DBAPIError, match="NOT NULL"):
        stored_entry(before, "l9", event_id="ev1", payment_id="p1", kind="CAPTURE")
    before.rollback()


@pytest.mark.parametrize("bad", ["composite", "REAL", "Mock", "", "unknown"])
def test_the_origin_is_a_closed_set(before, bad):
    up(before)

    with pytest.raises(DBAPIError, match="CHECK"):
        stored_payment(before, "p9", ref="simpay_9", provider_kind=bad)
    before.rollback()


@pytest.mark.parametrize("good", ["mock", "sandbox", "real"])
def test_the_three_origins_are_accepted(before, good):
    up(before)

    stored_payment(before, "p9", ref="simpay_9", provider_kind=good)

    assert kinds(before, "payments")["p9"] == good


# --- La guarda: no se rellena `mock` sobre lo que no se puede justificar
# ----------------------------------------------------


@pytest.mark.parametrize("what", ["payment", "event"])
def test_it_refuses_to_backfill_and_changes_nothing_when_a_provider_is_not_the_simulator(before, what):
    if what == "payment":
        stored_payment(before, "p7", provider="some-real-gateway", ref="gw_1")
    else:
        stored_event(before, "ev7", payment_id=None, provider="some-real-gateway")
    before.commit()
    triggers_before, indexes_before = triggers(before), index_sql(before)
    columns_before = {table: set(columns(before, table)) for table in TABLES}

    with pytest.raises(RuntimeError, match="refusing to backfill mock"):
        run(before, migration(), "upgrade")

    assert {table: set(columns(before, table)) for table in TABLES} == columns_before, "no partial modification"
    assert triggers(before) == triggers_before and index_sql(before) == indexes_before


# --- Los disparadores del registro sobreviven (la trampa de SQLite)
# -----------------------------------------------------


def test_the_ledger_stays_append_only_after_every_step(before):
    assert APPEND_ONLY <= triggers(before)

    for step in ("upgrade", "downgrade", "upgrade"):
        (up if step == "upgrade" else down)(before)
        assert APPEND_ONLY <= triggers(before), f"the append-only triggers vanished after {step}"
        with pytest.raises(DBAPIError, match="append-only"):
            before.execute(sa.text(f"UPDATE {LEDGER} SET amount = 1 WHERE id = 'l1'"))
        before.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            before.execute(sa.text(f"DELETE FROM {LEDGER} WHERE id = 'l1'"))
        before.rollback()


def test_the_ledger_trigger_text_is_the_one_of_the_model_and_of_the_ledger_migration(before):
    from app.db.models import revenue as ledger_model

    module = migration()

    assert module.LEDGER_APPEND_ONLY_SQLITE == ledger_model.APPEND_ONLY_SQLITE
    ledger_migration = load_migration("c4e8b1d9a273_revenue_ledger_entries.py")
    assert module.LEDGER_APPEND_ONLY_SQLITE == ledger_migration.APPEND_ONLY_SQLITE


def test_the_provider_kind_triggers_exist_and_make_it_immutable(before):
    up(before)
    assert IMMUTABLE <= triggers(before)

    with pytest.raises(DBAPIError, match="provider_kind is immutable"):
        before.execute(sa.text("UPDATE payments SET provider_kind = 'real' WHERE id = 'p1'"))
    before.rollback()
    with pytest.raises(DBAPIError, match="provider_kind is immutable"):
        before.execute(sa.text("UPDATE payment_events SET provider_kind = 'sandbox' WHERE id = 'ev3'"))
    before.rollback()
    # Lo que no cambia el origen pasa: otro campo, o el mismo valor.
    before.execute(sa.text("UPDATE payments SET last_failure_code = 'x' WHERE id = 'p1'"))
    before.execute(sa.text("UPDATE payments SET provider_kind = 'mock' WHERE id = 'p1'"))
    before.execute(sa.text("UPDATE payment_events SET processing_status = 'STALE' WHERE id = 'ev3'"))


def test_the_provider_kind_trigger_text_of_the_migration_and_of_the_model_is_the_same():
    module = migration()

    assert (
        module.PROVIDER_KIND_IMMUTABLE_FUNCTION_POSTGRESQL == payment_model.PROVIDER_KIND_IMMUTABLE_FUNCTION_POSTGRESQL
    )
    for table in ("payments", "payment_events"):
        assert module.provider_kind_immutable_trigger_postgresql(table) == (
            payment_model.provider_kind_immutable_trigger_postgresql(table)
        )
        assert module.provider_kind_immutable_trigger_sqlite(table) == (
            payment_model.provider_kind_immutable_trigger_sqlite(table)
        )


# --- Los índices parciales y las identidades (F12, B-parcial)
# ---------------------------------------------------------------


def test_every_index_survives_except_the_two_identities_that_now_carry_the_origin(before):
    indexes_before = index_sql(before)
    up(before)
    indexes_after = index_sql(before)

    assert set(indexes_before) <= set(indexes_after), f"lost: {sorted(set(indexes_before) - set(indexes_after))}"
    changed = {name for name in indexes_before if indexes_before[name] != indexes_after[name]}
    assert changed == {"uq_payments_provider_payment_ref"}, "only the payment identity changes"
    partial = {name for name, sql in indexes_after.items() if " WHERE " in sql}
    assert {
        "uq_payments_one_succeeded_per_order",
        "uq_payments_one_active_attempt_per_order",
        "uq_payments_provider_payment_ref",
        "uq_refunds_provider_refund_ref",
        "ix_payment_events_received",
        "uq_revenue_entries_one_capture_per_payment",
        "uq_revenue_entries_one_entry_per_refund",
    } <= partial, "the partial indexes keep their WHERE clause"


def test_the_identities_carry_the_origin_and_refunds_do_not(before):
    up(before)

    payments_ref = index_sql(before)["uq_payments_provider_payment_ref"]
    assert (
        "provider, provider_kind, provider_payment_ref" in payments_ref
        and "WHERE provider_payment_ref IS NOT NULL" in payments_ref
    )
    uniques = {u["name"]: u["column_names"] for u in sa.inspect(before).get_unique_constraints("payment_events")}
    assert uniques["uq_payment_events_provider_event"] == ["provider", "provider_kind", "provider_event_id"]
    refunds_ref = index_sql(before)["uq_refunds_provider_refund_ref"]
    assert "provider_kind" not in refunds_ref, "B-parcial: refunds keep (provider, provider_refund_ref)"
    assert "provider_kind" not in columns(before, "refunds"), "refunds never get a provider_kind column"


def test_downgrade_restores_the_previous_identities(before):
    up(before)
    down(before)

    assert "provider_kind" not in index_sql(before)["uq_payments_provider_payment_ref"]
    uniques = {u["name"]: u["column_names"] for u in sa.inspect(before).get_unique_constraints("payment_events")}
    assert uniques["uq_payment_events_provider_event"] == ["provider", "provider_event_id"]
    assert APPEND_ONLY <= triggers(before) and not (IMMUTABLE & triggers(before))


# --- Claves compuestas, restricciones y paridad con el modelo
# --------------------------------------------------------------


def test_the_composite_foreign_keys_and_constraints_exist(before):
    up(before)

    inspector = sa.inspect(before)
    for name, (table, local, target) in NEW_FOREIGN_KEYS.items():
        found = [fk for fk in inspector.get_foreign_keys(table) if fk["name"] == name]
        assert len(found) == 1, name
        assert found[0]["constrained_columns"] == local and found[0]["referred_table"] == target
    constraint_names = {
        c["name"]
        for table in TABLES
        for c in inspector.get_check_constraints(table) + inspector.get_unique_constraints(table)
    }
    assert NEW_CONSTRAINT_NAMES <= constraint_names


def test_the_migrated_tables_are_what_the_model_declares(before):
    up(before)

    assert_migration_matches_model(before, (*TABLES, "refunds"))


def test_downgrade_leaves_the_schema_as_before(before):
    indexes_before = index_sql(before)
    fks_before = {table: fk_names(before, table) for table in TABLES}
    up(before)
    down(before)

    assert index_sql(before) == indexes_before
    assert {table: fk_names(before, table) for table in TABLES} == fks_before
    assert not NEW_CONSTRAINT_NAMES & {
        c["name"] for table in TABLES for c in sa.inspect(before).get_check_constraints(table)
    }


def test_it_refuses_to_go_down_when_a_row_is_not_mock_and_changes_nothing(before):
    up(before)
    stored_payment(before, "p8", ref="sbx_1", provider_kind="sandbox")
    before.commit()

    with pytest.raises(RuntimeError, match="refusing to downgrade"):
        run(before, migration(), "downgrade")

    for table in TABLES:
        assert "provider_kind" in columns(before, table), "nothing was dropped"
    assert IMMUTABLE <= triggers(before)


# --- RLS, DML y orden (la forma de PostgreSQL, sin PostgreSQL)
# -------------------------------------------------------------------


@pytest.mark.parametrize("roles", [True, False])
def test_it_does_not_touch_row_level_security_nor_issue_any_dml(monkeypatch, roles):
    """No hay tablas nuevas: la RLS se hereda. Y la migración jamás hace `UPDATE`/`DELETE`/`INSERT`/`TRUNCATE`: el
    relleno
    es el `DEFAULT` temporal, que no dispara los disparadores *append-only*."""
    module = migration()
    recorder = RecordingOp(supabase_roles=roles)
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    statements = [" ".join(s.split()) for s in recorder.statements]
    assert statements, "the migration executes statements"
    for s in statements:
        upper = s.upper()
        assert "ROW LEVEL SECURITY" not in upper and "POLICY" not in upper and "FORCE" not in upper, s
        assert not upper.startswith(("UPDATE ", "DELETE ", "INSERT ", "TRUNCATE ")), s
    assert statements[0].startswith("DO $$ BEGIN"), "the guard runs before anything is changed"
    assert any(
        "CREATE OR REPLACE FUNCTION provider_kind_immutable()" in s and "SET search_path = pg_catalog" in s
        for s in statements
    )
    assert sum("provider_kind_immutable BEFORE UPDATE OF provider_kind" in s for s in statements) == 2
