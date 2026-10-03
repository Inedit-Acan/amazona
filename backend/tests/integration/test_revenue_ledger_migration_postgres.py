"""La migración del registro de ingresos verificados sobre un PostgreSQL de verdad (Milestone 45, ADR 0030 §8 y §14).

SQLite no tiene `plpgsql`, ni `TRUNCATE` con trigger, ni RLS: lo que es propio de PostgreSQL solo se demuestra aquí. La
base efímera nace con el esquema de los modelos (que ya crea la tabla y su trigger con el DDL del modelo); la prueba la
**quita** y ejecuta la migración de verdad, y comprueba que deja exactamente lo mismo que el modelo, que rechaza
`UPDATE`, `DELETE` y `TRUNCATE`, que activa RLS, que baja sin tocar un solo hecho de pago y que vuelve a subir.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from order_test_support import add_product
from payment_test_support import ScriptedPaymentProvider, add_order, deliver, start_attempt
from pg_test_support import ephemeral_postgres
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry
from app.payments.port import PaymentEventType
from app.revenue.ledger import RevenueLedger

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
FILE = "c4e8b1d9a273_revenue_ledger_entries.py"
TABLE = "revenue_ledger_entries"
FUNCTION = "revenue_ledger_entries_append_only"

TRIGGER_DEFINITIONS = f"""
    SELECT t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
    WHERE t.tgrelid = '{TABLE}'::regclass AND NOT t.tgisinternal ORDER BY t.tgname
"""
FUNCTION_DEFINITION = f"SELECT pg_get_functiondef('{FUNCTION}'::regproc)"


def migration():
    spec = importlib.util.spec_from_file_location("revenue_ledger_migration", VERSIONS / FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(engine, direction: str) -> None:
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(migration(), direction)()
        conn.commit()


def scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def exists(engine, kind: str, name: str) -> bool:
    if kind == "table":
        return bool(scalar(engine, f"SELECT to_regclass('public.{name}') IS NOT NULL"))
    return bool(scalar(engine, f"SELECT count(*) FROM pg_proc WHERE proname = '{name}'"))


@pytest.fixture()
def engine():
    """Una base con el esquema del modelo **sin** el registro: lo que habría antes de esta migración."""
    with ephemeral_postgres() as built:
        with built.connect() as conn:
            model_triggers = conn.execute(text(TRIGGER_DEFINITIONS)).all()
            model_function = conn.execute(text(FUNCTION_DEFINITION)).scalar()
            conn.execute(text(f"DROP TABLE {TABLE}"))
            conn.execute(text(f"DROP FUNCTION {FUNCTION}()"))
            conn.commit()
        built.model_definitions = (model_triggers, model_function)  # type: ignore[attr-defined]
        yield built


def capture(engine) -> tuple[str, str]:
    """Un cobro capturado por la puerta de eventos; devuelve (cobro, evento)."""
    provider = ScriptedPaymentProvider()
    with Session(engine) as db:
        payment = start_attempt(db, add_order(db, add_product(db)), provider)
        deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
        event = db.scalars(select(PaymentEvent)).one()
        return payment.id, event.id


def test_upgrade_leaves_exactly_what_the_model_creates(engine):
    assert not exists(engine, "table", TABLE) and not exists(engine, "function", FUNCTION)

    run(engine, "upgrade")

    model_triggers, model_function = engine.model_definitions
    with engine.connect() as conn:
        assert conn.execute(text(TRIGGER_DEFINITIONS)).all() == model_triggers
        assert conn.execute(text(FUNCTION_DEFINITION)).scalar() == model_function
    assert {name for name, _ in model_triggers} == {
        "revenue_ledger_entries_append_only_row",
        "revenue_ledger_entries_append_only_truncate",
    }


def test_rls_is_enabled_and_not_forced(engine):
    run(engine, "upgrade")

    with engine.connect() as conn:
        enabled, forced = conn.execute(
            text(f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = '{TABLE}'::regclass")
        ).one()
    assert (enabled, forced) == (True, False), "RLS on, never forced: the backend owns the tables (ADR 0003)"


def test_the_migrated_ledger_projects_a_capture_and_rejects_update_delete_and_truncate(engine):
    run(engine, "upgrade")
    payment_id, event_id = capture(engine)

    with Session(engine) as db:
        (entry,) = db.scalars(select(RevenueLedgerEntry)).all()
        assert (entry.payment_id, entry.payment_event_id, entry.classification) == (
            payment_id,
            event_id,
            "ORDER_PAYMENT",
        )
    for statement in (
        f"UPDATE {TABLE} SET amount = 1",
        f"DELETE FROM {TABLE}",
        f"TRUNCATE {TABLE}",
    ):
        with pytest.raises(DBAPIError, match="append-only") as raised:
            with engine.begin() as conn:
                conn.execute(text(statement))
        assert getattr(raised.value.orig, "sqlstate", None) == "23001", "restrict_violation"
    assert scalar(engine, f"SELECT count(*) FROM {TABLE}") == 1 and scalar(engine, f"SELECT amount FROM {TABLE}") == 50


def test_downgrade_removes_the_ledger_the_function_and_the_triggers_without_touching_the_facts(engine):
    run(engine, "upgrade")
    payment_id, _ = capture(engine)

    run(engine, "downgrade")

    assert not exists(engine, "table", TABLE) and not exists(engine, "function", FUNCTION)
    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        assert payment is not None and payment.status == "SUCCEEDED" and float(payment.captured_amount) == 50.0
        assert db.scalars(select(PaymentEvent)).one().processing_status == "APPLIED"


def test_it_can_be_applied_again_after_a_downgrade(engine):
    run(engine, "upgrade")
    run(engine, "downgrade")

    run(engine, "upgrade")

    assert exists(engine, "table", TABLE) and exists(engine, "function", FUNCTION)
    capture(engine)
    assert scalar(engine, f"SELECT count(*) FROM {TABLE}") == 1


def test_it_does_not_backfill_a_payment_captured_before_it(engine, monkeypatch):
    # Un cobro anterior al registro: la captura se aplicó cuando la tabla todavía no existía.
    monkeypatch.setattr(RevenueLedger, "record_capture", lambda self, **kwargs: None)
    payment_id, _ = capture(engine)
    monkeypatch.undo()

    run(engine, "upgrade")

    assert scalar(engine, f"SELECT count(*) FROM {TABLE}") == 0, "no backfill: outside_ledger (ADR 0030 §13)"
    with Session(engine) as db:
        assert db.get(Payment, payment_id).status == "SUCCEEDED"
