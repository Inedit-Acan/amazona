"""La migración 44.ª sobre un PostgreSQL de verdad, con la **cadena entera de Alembic** (Milestone 46, ADR 0031 §7 y
§8).

SQLite no tiene `plpgsql`, ni `TRUNCATE` con disparador, ni RLS, ni transacciones de verdad. Y las pruebas de modelos
crean el
esquema con `create_all`, que no ejecuta las migraciones. Aquí se hace lo que hace el CI: una base **vacía**, `alembic
upgrade`
hasta la revisión anterior (con sus disparadores y su RLS reales), **filas históricas**, y la 44.ª. Se ejecuta en un
**subproceso** (como el CI) para que el `fileConfig` de `env.py` no toque el registro de logs de las demás pruebas.

Lo que se demuestra: el relleno `mock`, el esquema final **sin `DEFAULT`**, los disparadores *append-only* del registro
intactos, la RLS sin debilitar, los índices parciales conservados, las identidades por origen (F12, B-parcial), las
claves
ajenas compuestas, la inmutabilidad, las dos guardas y que bajar deja el esquema **exactamente** como estaba.

Solo contra un PostgreSQL local o efímero: si `DATABASE_URL` apunta a otro sitio, o no hay PostgreSQL alcanzable, se
omite.
"""

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import get_settings

BACKEND = Path(__file__).resolve().parents[2]
BEFORE = "e5a1d7c93b04"
AFTER = "b7e4a1c9d052"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TABLES = ("payments", "payment_events", "refunds", "revenue_ledger_entries")
LEDGER = "revenue_ledger_entries"
ALEMBIC_INI = BACKEND / "alembic.ini"


@contextmanager
def empty_database():
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL")
    if url.host not in LOCAL_HOSTS:
        pytest.skip("these tests create and drop a database: only against a local or ephemeral PostgreSQL")
    name = f"amazona_prov_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"no reachable PostgreSQL at DATABASE_URL: {exc}")
    except Exception as exc:  # noqa: BLE001 - sin permiso para crear bases: no es un fallo del producto
        admin.dispose()
        pytest.skip(f"cannot create a scratch database here: {exc}")
    try:
        yield url.set(database=name)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic(url: URL, *args: str, tmp: Path) -> subprocess.CompletedProcess:
    """`alembic` como lo corre el CI, contra la base efímera. Desde un directorio **sin `.env`**: la configuración
    sale del
    entorno, no de ningún fichero local."""
    env = {
        **os.environ,
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "ENVIRONMENT": "development",
        "SUPABASE_URL": "",
        "SUPABASE_ANON_KEY": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def must(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, f"alembic failed:\n{result.stderr[-1500:]}"


@pytest.fixture()
def database(tmp_path):
    with empty_database() as url:
        yield url, tmp_path


def history(conn: Connection) -> None:
    """Hechos históricos en el esquema **anterior** a la 44.ª: dos pedidos cobrados, un reembolso, cuatro eventos (uno
    `UNMATCHED`) y tres entradas del registro."""
    ts = "'2026-10-03T10:00:00+00'"
    for order in ("o1", "o2"):
        conn.execute(text(
            "INSERT INTO orders (id, customer_ref, market, currency, amount_due, status, is_simulated, correlation_id, "
            f"created_at, updated_at) VALUES ('{order}', 'sim_{order}', 'eu', 'EUR', 50, 'PAID', true, 'c', {ts}, {ts})"
        ))  # fmt: skip
    for pid, order, ref, refunded in (("p1", "o1", "simpay_1", 10), ("p2", "o2", "simpay_2", 0)):
        conn.execute(text(
            "INSERT INTO payments (id, order_id, attempt_number, provider, status, amount, currency, "
            "provider_payment_ref, "
            "captured_amount, refund_committed_amount, refunded_amount, correlation_id, created_at, updated_at) "
            f"VALUES ('{pid}', '{order}', 1, 'simulated-payments', 'SUCCEEDED', 50, 'EUR', '{ref}', 50, {refunded}, "
            f"{refunded}, 'c', {ts}, {ts})"
        ))  # fmt: skip
    conn.execute(text(
        "INSERT INTO refunds (id, payment_id, provider, origin, status, amount, currency, reason, provider_refund_ref, "
        f"correlation_id, requested_at, finished_at, created_at, updated_at) VALUES ('r1', 'p1', 'simulated-payments', "
        f"'OPERATOR', 'SUCCEEDED', 10, 'EUR', 'customer_request', 'simref_1', 'c', {ts}, {ts}, {ts}, {ts})"
    ))  # fmt: skip
    for eid, pid, etype, status, amount in (
        ("ev1", "p1", "payment.succeeded", "APPLIED", 50),
        ("ev2", "p2", "payment.succeeded", "APPLIED", 50),
        ("ev3", None, "payment.succeeded", "UNMATCHED", 7),
        ("ev4", "p1", "refund.succeeded", "APPLIED", 10),
    ):
        payment_id = f"'{pid}'" if pid else "NULL"
        conn.execute(text(
            "INSERT INTO payment_events (id, provider, provider_event_id, event_type, payment_id, amount, currency, "
            "occurred_at, received_at, payload_hash, processing_status) VALUES "
            f"('{eid}', 'simulated-payments', 'evt-{eid}', '{etype}', {payment_id}, {amount}, 'EUR', {ts}, {ts}, 'h', "
            f"'{status}')"
        ))  # fmt: skip
    for lid, kind, eid, pid, order, refund, capture in (
        ("l1", "CAPTURE", "ev1", "p1", "o1", None, None),
        ("l2", "CAPTURE", "ev2", "p2", "o2", None, None),
        ("l3", "REFUND", "ev4", "p1", "o1", "'r1'", "'l1'"),
    ):
        amount = 10 if kind == "REFUND" else 50
        conn.execute(text(
            f"INSERT INTO {LEDGER} (id, kind, classification, payment_event_id, payment_id, order_id, refund_id, "
            f"capture_entry_id, amount, currency, occurred_at, recorded_at) VALUES "
            f"('{lid}', '{kind}', 'ORDER_PAYMENT', "
            f"'{eid}', '{pid}', '{order}', {refund or 'NULL'}, {capture or 'NULL'}, {amount}, 'EUR', {ts}, {ts})"
        ))  # fmt: skip


def snapshot(conn: Connection) -> dict:
    """Todo lo que la migración podría estropear sin avisar: columnas y defectos, índices (con su `WHERE`),
    restricciones,
    disparadores (con su definición), funciones, RLS y políticas."""
    names = ", ".join(f"'{t}'" for t in TABLES)
    return {
        "columns": {
            (r[0], r[1]): (r[2], r[3], r[4])
            for r in conn.execute(
                text(
                    "SELECT table_name, column_name, is_nullable, column_default, data_type "
                    "FROM information_schema.columns "
                    f"WHERE table_schema = 'public' AND table_name IN ({names})"
                )
            )  # fmt: skip
        },
        "indexes": {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    f"SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename IN ({names})"
                )
            )  # fmt: skip
        },
        "constraints": {
            (r[0], r[1]): (r[2], r[3])
            for r in conn.execute(
                text(
                    "SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
                    f"WHERE conrelid::regclass::text IN ({names})"
                )
            )  # fmt: skip
        },
        "triggers": {
            (r[0], r[1]): r[2]
            for r in conn.execute(
                text(
                    "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                    f"WHERE NOT tgisinternal AND tgrelid::regclass::text IN ({names})"
                )
            )  # fmt: skip
        },
        "functions": {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    "SELECT proname, pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
                    "AND proname IN ('revenue_ledger_entries_append_only', 'provider_kind_immutable')"
                )
            )  # fmt: skip
        },
        "rls": {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    f"WHERE relnamespace = 'public'::regnamespace AND relname IN ({names})"
                )
            )  # fmt: skip
        },
        "policies": sorted(
            tuple(r)
            for r in conn.execute(
                text(f"SELECT tablename, policyname, cmd, roles::text FROM pg_policies WHERE tablename IN ({names})")
            )  # fmt: skip
        ),
        "alembic": conn.execute(text("SELECT version_num FROM alembic_version")).scalar(),
    }


def refuses(conn: Connection, sql: str, contains: str, **params) -> None:
    """La base rechaza la sentencia, con un mensaje que la explica; la transacción sigue viva (punto de guardado)."""
    with pytest.raises(DBAPIError) as caught:
        with conn.begin_nested():
            conn.execute(text(sql), params)
    assert contains in str(caught.value.orig), f"expected {contains!r} in: {caught.value.orig}"


def payment(conn: Connection, pid: str, order: str, kind: str, ref: str | None, *, status: str = "OPEN") -> None:
    conn.execute(text(
        "INSERT INTO payments (id, order_id, attempt_number, provider, provider_kind, status, amount, currency, "
        "provider_payment_ref, correlation_id, created_at, updated_at) VALUES "
        "(:id, :o, 1, 'simulated-payments', :k, :s, "
        "50, 'EUR', :ref, 'c', now(), now())"
    ), {"id": pid, "o": order, "k": kind, "s": status, "ref": ref})  # fmt: skip


def an_event(conn: Connection, eid: str, kind: str, event_id: str, *, payment_id: str | None = None) -> None:
    conn.execute(text(
        "INSERT INTO payment_events (id, provider, provider_kind, provider_event_id, event_type, payment_id, "
        "occurred_at, "
        "received_at, payload_hash, processing_status) VALUES (:id, 'simulated-payments', :k, :e, 'payment.succeeded', "
        ":p, now(), now(), 'h', 'RECEIVED')"
    ), {"id": eid, "k": kind, "e": event_id, "p": payment_id})  # fmt: skip


def an_order(conn: Connection, order: str) -> None:
    conn.execute(text(
        "INSERT INTO orders (id, customer_ref, market, currency, amount_due, status, is_simulated, correlation_id, "
        "created_at, updated_at) VALUES (:o, :c, 'eu', 'EUR', 50, 'AWAITING_PAYMENT', true, 'c', now(), now())"
    ), {"o": order, "c": f"sim_{order}"})  # fmt: skip


# --- 1. Subir con historia, bajar, subir
# ---------------------------------------------------------------------------------------


def test_upgrade_with_history_downgrade_and_upgrade_again_leave_the_schema_exactly_where_it_should(database):
    url, tmp = database
    engine = create_engine(url)
    try:
        must(alembic(url, "upgrade", BEFORE, tmp=tmp))
        with engine.begin() as conn:
            history(conn)
            pre = snapshot(conn)
        assert pre["alembic"] == BEFORE
        assert {t for t, _ in pre["triggers"]} == {LEDGER}, "the ledger is the only table with triggers before"
        assert all(rls == (True, False) for rls in pre["rls"].values()), "RLS enabled by the migrations, never forced"

        must(alembic(url, "upgrade", AFTER, tmp=tmp))
        with engine.begin() as conn:
            post = snapshot(conn)
            kinds = {
                t: dict(conn.execute(text(f"SELECT id, provider_kind FROM {t}")).all()) for t in
                ("payments", "payment_events", LEDGER)
            }  # fmt: skip
            amounts = [str(a) for (a,) in conn.execute(text(f"SELECT amount FROM {LEDGER} ORDER BY id"))]

        assert post["alembic"] == AFTER
        # El relleno: todo lo histórico es `mock`, y no se perdió ni se tocó un solo hecho.
        assert kinds["payments"] == {"p1": "mock", "p2": "mock"}
        assert kinds["payment_events"] == {"ev1": "mock", "ev2": "mock", "ev3": "mock", "ev4": "mock"}
        assert kinds[LEDGER] == {"l1": "mock", "l2": "mock", "l3": "mock"}
        assert amounts == ["50.0000", "50.0000", "10.0000"]
        # El esquema final: NOT NULL y SIN `DEFAULT` en las tres; ninguna en `refunds`.
        for table in ("payments", "payment_events", LEDGER):
            assert post["columns"][(table, "provider_kind")][:2] == ("NO", None), table
        assert ("refunds", "provider_kind") not in post["columns"], "refunds never get a provider_kind"
        # Los disparadores del registro intactos (definición idéntica), y los nuevos de inmutabilidad.
        for key, definition in pre["triggers"].items():
            assert post["triggers"][key] == definition, f"trigger changed: {key}"
        assert (
            post["functions"]["revenue_ledger_entries_append_only"]
            == pre["functions"]["revenue_ledger_entries_append_only"]
        )
        assert {n for t, n in post["triggers"] if t in ("payments", "payment_events")} == {
            "payments_provider_kind_immutable",
            "payment_events_provider_kind_immutable",
        }
        assert "SET search_path TO 'pg_catalog'" in post["functions"]["provider_kind_immutable"]
        # RLS y políticas: ni un cambio.
        assert post["rls"] == pre["rls"] and post["policies"] == pre["policies"]
        # Índices: ninguno perdido; solo cambia la identidad del cobro, y todos los parciales conservan su `WHERE`.
        assert set(pre["indexes"]) <= set(post["indexes"])
        changed = {n for n in pre["indexes"] if pre["indexes"][n] != post["indexes"][n]}
        # (el de eventos es el índice que respalda la restricción única de `payment_events`: la misma identidad por
        # origen)
        assert changed == {"uq_payments_provider_payment_ref", "uq_payment_events_provider_event"}
        assert (
            "(provider, provider_kind, provider_payment_ref) WHERE (provider_payment_ref IS NOT NULL)"
            in (post["indexes"]["uq_payments_provider_payment_ref"])
        )
        assert post["indexes"]["uq_refunds_provider_refund_ref"] == pre["indexes"]["uq_refunds_provider_refund_ref"]
        for name, definition in pre["indexes"].items():
            if " WHERE " in definition and name != "uq_payments_provider_payment_ref":
                assert post["indexes"][name] == definition, name
        # Restricciones: las nuevas están; las anteriores, salvo la identidad del evento, iguales.
        assert post["constraints"][("payment_events", "uq_payment_events_provider_event")][1] == (
            "UNIQUE (provider, provider_kind, provider_event_id)"
        )
        for key in (
            ("payments", "ck_payments_provider_kind"), ("payment_events", "ck_payment_events_provider_kind"),
            (LEDGER, "ck_revenue_entries_provider_kind"), ("payments", "uq_payments_id_provider_kind"),
            ("payment_events", "uq_payment_events_id_provider_kind"),
            ("payment_events", "fk_payment_events_payment_kind"),
            (LEDGER, "fk_revenue_entries_payment_kind"), (LEDGER, "fk_revenue_entries_event_kind"),
        ):  # fmt: skip
            assert key in post["constraints"], key
        for key, value in pre["constraints"].items():
            if key != ("payment_events", "uq_payment_events_provider_event"):
                assert post["constraints"][key] == value, key

        # Bajar: el esquema vuelve a ser EXACTAMENTE el anterior, con los datos intactos.
        must(alembic(url, "downgrade", BEFORE, tmp=tmp))
        with engine.begin() as conn:
            down = snapshot(conn)
            assert conn.execute(text("SELECT count(*) FROM payments")).scalar() == 2
            assert conn.execute(text(f"SELECT count(*) FROM {LEDGER}")).scalar() == 3
        assert down == pre, {k: (down[k], pre[k]) for k in pre if down[k] != pre[k]}

        # Y subir otra vez: lo mismo que la primera vez.
        must(alembic(url, "upgrade", AFTER, tmp=tmp))
        with engine.begin() as conn:
            again = snapshot(conn)
        assert again == post
    finally:
        engine.dispose()


# --- 2. Las reglas de origen las impone la base
# --------------------------------------------------------------------------------


def test_the_database_enforces_the_origin_rules_with_the_real_chain(database):
    url, tmp = database
    engine = create_engine(url)
    try:
        must(alembic(url, "upgrade", BEFORE, tmp=tmp))
        with engine.begin() as conn:
            history(conn)
        must(alembic(url, "upgrade", AFTER, tmp=tmp))
        with engine.begin() as conn:
            for order in ("o5", "o6", "o7", "o8"):
                an_order(conn, order)

            # Sin `DEFAULT` y cerrado.
            refuses(
                conn,
                "INSERT INTO payments (id, order_id, attempt_number, provider, status, amount, currency, "
                "correlation_id, created_at, updated_at) VALUES ('px', 'o5', 1, 'simulated-payments', 'OPEN', 50, "
                "'EUR', 'c', now(), now())",
                "not-null",
            )
            for bad in ("composite", "REAL", ""):
                with pytest.raises(DBAPIError, match="ck_payments_provider_kind"):
                    with conn.begin_nested():
                        payment(conn, "pbad", "o5", bad, "x")

            # F12 / B-parcial. (1) mismo proveedor y referencia, mismo origen: rechazado. (2) otro origen: otro cobro.
            payment(conn, "p5", "o5", "sandbox", "simpay_1")  # `simpay_1` ya es de p1, que es `mock`
            with pytest.raises(DBAPIError, match="uq_payments_provider_payment_ref"):
                with conn.begin_nested():
                    payment(conn, "p6", "o6", "mock", "simpay_1")
            # (3) y (4): el mismo id de evento en dos orígenes son dos eventos; en el mismo origen, uno.
            an_event(conn, "ev5", "sandbox", "evt-ev1")  # `evt-ev1` ya es de ev1 (`mock`)
            an_event(conn, "ev6", "real", "evt-ev1")
            with pytest.raises(DBAPIError, match="uq_payment_events_provider_event"):
                with conn.begin_nested():
                    an_event(conn, "ev7", "sandbox", "evt-ev1")

            # (5) UNMATCHED con tipo conocido, sin cobro. (6) un evento de otro origen no se enlaza a un cobro.
            an_event(conn, "ev8", "real", "evt-unmatched")
            refuses(
                conn, "UPDATE payment_events SET payment_id = 'p5' WHERE id = 'ev8'", "fk_payment_events_payment_kind"
            )
            refuses(
                conn, "UPDATE payment_events SET payment_id = 'p5' WHERE id = 'ev3'", "fk_payment_events_payment_kind"
            )
            conn.execute(text("UPDATE payment_events SET payment_id = 'p5' WHERE id = 'ev5'"))  # sandbox ↔ sandbox
            an_event(conn, "ev9", "sandbox", "evt-new", payment_id="p5")
            refuses(
                conn,
                "INSERT INTO payment_events (id, provider, provider_kind, provider_event_id, event_type, payment_id, "
                "occurred_at, received_at, payload_hash, processing_status) VALUES ('evx', 'simulated-payments', "
                "'real', 'evt-x', 'payment.succeeded', 'p5', now(), now(), 'h', 'RECEIVED')",
                "fk_payment_events_payment_kind",
            )

            # (7) el registro: la entrada es del origen de su cobro y de su evento.
            ledger = (
                "INSERT INTO revenue_ledger_entries (id, kind, classification, payment_event_id, payment_id, order_id, "
                "amount, currency, occurred_at, recorded_at, provider_kind) VALUES "
                "('{id}', 'CAPTURE', 'MISMATCH_RECEIPT', "
                "'{event}', 'p5', 'o5', 1, 'EUR', now(), now(), '{kind}')"
            )
            # Cada caso viola UNA sola clave (PostgreSQL no garantiza cuál evalúa primero): `ev3` es un evento `mock`.
            refuses(
                conn, ledger.format(id="lx", event="ev3", kind="mock"), "fk_revenue_entries_payment_kind"
            )  # cobro sandbox
            refuses(
                conn, ledger.format(id="lz", event="ev3", kind="sandbox"), "fk_revenue_entries_event_kind"
            )  # evento mock
            conn.execute(text(ledger.format(id="ly", event="ev9", kind="sandbox")))  # la coherente entra

            # (8) nada se reescribe después de persistir.
            refuses(
                conn,
                "UPDATE payments SET provider_kind = 'real' WHERE id = 'p1'",
                "payments.provider_kind is immutable",
            )
            refuses(
                conn,
                "UPDATE payment_events SET provider_kind = 'real' WHERE id = 'ev1'",
                "payment_events.provider_kind is immutable",
            )
            refuses(conn, "UPDATE revenue_ledger_entries SET provider_kind = 'real' WHERE id = 'l1'", "append-only")
            refuses(conn, "DELETE FROM revenue_ledger_entries WHERE id = 'l1'", "append-only")
            refuses(conn, "TRUNCATE revenue_ledger_entries", "append-only")
            conn.execute(text("UPDATE payments SET provider_kind = 'mock', last_failure_code = 'x' WHERE id = 'p1'"))

            # Refund: sin columna. Su colisión de referencia entre orígenes NO se mezcla: se rechaza (identidad por
            # proveedor).
            with pytest.raises(DBAPIError, match="uq_refunds_provider_refund_ref"):
                with conn.begin_nested():
                    conn.execute(text(
                        "INSERT INTO refunds (id, payment_id, provider, origin, status, amount, currency, reason, "
                        "provider_refund_ref, correlation_id, requested_at, created_at, updated_at) VALUES "
                        "('r5', 'p5', "
                        "'simulated-payments', 'PROVIDER', 'REQUESTED', 5, 'EUR', 'customer_request', 'simref_1', 'c', "
                        "now(), now(), now())"
                    ))  # fmt: skip
    finally:
        engine.dispose()


# --- 3. Las guardas
# ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["payment", "event"])
def test_it_refuses_to_backfill_and_changes_nothing_if_a_row_is_not_the_simulators(database, where):
    url, tmp = database
    engine = create_engine(url)
    try:
        must(alembic(url, "upgrade", BEFORE, tmp=tmp))
        with engine.begin() as conn:
            history(conn)
            if where == "payment":
                conn.execute(text("UPDATE payments SET provider = 'some-real-gateway' WHERE id = 'p2'"))
            else:
                conn.execute(text("UPDATE payment_events SET provider = 'some-real-gateway' WHERE id = 'ev3'"))
            pre = snapshot(conn)

        result = alembic(url, "upgrade", AFTER, tmp=tmp)

        assert result.returncode != 0 and "refusing to backfill mock" in result.stderr
        with engine.begin() as conn:
            assert snapshot(conn) == pre, "no partial modification: the guard runs before anything is changed"
    finally:
        engine.dispose()


def test_it_refuses_to_go_down_if_a_row_is_not_mock_and_changes_nothing(database):
    url, tmp = database
    engine = create_engine(url)
    try:
        must(alembic(url, "upgrade", BEFORE, tmp=tmp))
        with engine.begin() as conn:
            history(conn)
        must(alembic(url, "upgrade", AFTER, tmp=tmp))
        with engine.begin() as conn:
            an_order(conn, "o5")
            payment(conn, "p5", "o5", "sandbox", "sbx_1")
            pre = snapshot(conn)

        result = alembic(url, "downgrade", BEFORE, tmp=tmp)

        assert result.returncode != 0 and "refusing to downgrade" in result.stderr
        with engine.begin() as conn:
            assert snapshot(conn) == pre
    finally:
        engine.dispose()
