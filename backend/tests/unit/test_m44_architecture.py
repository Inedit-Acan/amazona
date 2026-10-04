"""Las fronteras de M44, hechas cumplir por pruebas (Milestone 44, ADR 0028).

Una convención se olvida; una prueba que recorre el código, no. Las promesas que no tenían guardián:

1. El dinero no pasa por `float`: se recorre el árbol sintáctico del código de pedidos, cobros y fulfillment, y las
pocas
   fronteras heredadas (el libro de presupuesto y `ExternalAction.amount` siguen en `float`) están nombradas, una a una.
2. Solo los observadores registrados proyectan una `ExternalAction` a su dominio, y son exactamente los tres previstos.
3. Ninguna ruta `GET` escribe (comprobado en el código de cada una; la prueba dinámica está en
   `test_m44_contract_gaps.py`).
4. Ningún adaptador simulado puede hablar con la red: ni siquiera importa una biblioteca que sepa hacerlo.
5. Ninguna prueba carga `backend/.env` ni nombra la base real de Supabase, y la base de las pruebas de carreras solo
puede
   ser local.
6. El cuerpo bruto de un webhook no se guarda en ninguna columna.
"""

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import Float, Numeric, String, Text

import app.db.models  # noqa: F401 - registra todas las tablas
from app.actions.observers import REGISTERED
from app.core.config import Settings
from app.db.base import Base
from app.main import app

APP = Path(__file__).resolve().parents[2] / "app"
TESTS = Path(__file__).resolve().parents[1]

# --- 1. Dinero sin float
# ------------------------------------------------------------------------------------------------

#: Dónde vive el dinero de M44.
MONEY_CODE = [
    *sorted((APP / "orders").glob("*.py")),
    *sorted((APP / "payments").glob("*.py")),
    *sorted((APP / "payments" / "providers").glob("*.py")),
    APP / "api" / "orders.py",
    APP / "api" / "payments.py",
    APP / "api" / "fulfillments.py",
    APP / "db" / "models" / "order.py",
    APP / "db" / "models" / "payment.py",
    APP / "db" / "models" / "fulfillment.py",
]

# : Las fronteras con lo que el repositorio todavía guarda como `float`, una a una y con su motivo. Una nueva aparición
# es un : fallo: o se quita, o se añade aquí **con su motivo** (y alguien la lee en la revisión).
LEGACY_FLOAT_BOUNDARIES = {
    (
        "orders/service.py",
        "Money.from_legacy_float",
    ): "el precio de una cotización de proveedor se guarda en una columna `Float` legada",
    (
        "orders/simulated_fulfilment.py",
        "legacy_float",
    ): "el coste que declara el adaptador cruza a `ExternalAction.amount` y al libro de presupuesto, que son `float`",
    (
        "api/orders.py",
        "float:name",
    ): "la anotación de `_money` admite `float`, pero lo convierte con `Decimal(str())` y ningún llamador lo pasa "
    "(solo `Decimal` de columnas `Numeric`): apretar la anotación es deuda menor anotada, no un camino abierto",
}


def float_uses(path: Path) -> set[tuple[str, str]]:
    """Usos de `float` en un fichero: llamadas, anotaciones, literales y columnas `Float`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    uses: set[tuple[str, str]] = set()
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "float":
            uses.add(("float", "name"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, float) and id(node) not in docstrings:
            uses.add(("float", f"literal {node.value}"))
        elif isinstance(node, ast.Name) and node.id == "Float":
            uses.add(("Float", "column"))
        elif isinstance(node, ast.Attribute) and node.attr in ("from_legacy_float", "legacy_float"):
            uses.add((node.attr if node.attr == "legacy_float" else f"Money.{node.attr}", "call"))
        elif isinstance(node, ast.Name) and node.id == "legacy_float":
            uses.add(("legacy_float", "call"))
    return uses


def test_the_money_of_orders_payments_and_fulfilment_never_goes_through_a_float():
    found: dict[tuple[str, str], list[str]] = {}
    for path in MONEY_CODE:
        relative = path.relative_to(APP).as_posix()
        for kind, detail in float_uses(path):
            if kind in ("Money.from_legacy_float", "legacy_float"):
                found.setdefault((relative, kind), []).append(detail)
            else:
                found.setdefault((relative, f"{kind}:{detail}"), []).append(detail)

    unknown = {key: v for key, v in found.items() if key not in LEGACY_FLOAT_BOUNDARIES}
    assert not unknown, (
        "float in the money code of M44 (a float brings back the rounding error `Money` exists to remove): "
        f"{sorted(unknown)}; the legacy boundaries are named in LEGACY_FLOAT_BOUNDARIES"
    )
    # Y cada frontera nombrada sigue existiendo: si se elimina, se quita de la lista (la lista solo puede menguar).
    stale = [key for key in LEGACY_FLOAT_BOUNDARIES if key not in found]
    assert not stale, f"legacy boundaries that no longer exist, remove them: {stale}"


def test_every_money_column_of_the_m44_tables_is_an_exact_decimal_with_four_places():
    named_like_money = ("amount", "price", "cost", "total", "due", "captured", "committed", "refunded")
    tables = ("orders", "order_items", "payments", "payment_events", "refunds", "fulfillments", "fulfillment_items")
    found: set[str] = set()
    for table in tables:
        for column in Base.metadata.tables[table].columns:
            if not any(word in column.name for word in named_like_money):
                continue
            if any(word in column.name for word in ("provenance", "source", "currency", "code", "reason")):
                continue  # se llaman parecido, pero describen el dinero; no lo contienen
            found.add(f"{table}.{column.name}")
            assert not isinstance(column.type, Float), f"{table}.{column.name} is a Float"
            assert isinstance(column.type, Numeric), f"{table}.{column.name} is {column.type}"
            assert (column.type.precision, column.type.scale) == (18, 4), f"{table}.{column.name} is {column.type}"
    # El conjunto exacto: una columna de dinero nueva obliga a decidir aquí que también es decimal exacto.
    assert found == {
        "orders.amount_due",
        "order_items.unit_price",
        "order_items.line_total",
        "order_items.unit_cost",
        "payments.amount",
        "payments.captured_amount",
        "payments.refund_committed_amount",
        "payments.refunded_amount",
        "payment_events.amount",
        "refunds.amount",
    }, sorted(found)


# --- 2. Quién proyecta una acción al dominio
# -------------------------------------------------------------------------------


def test_exactly_three_observers_project_an_external_action_into_its_domain():
    assert sorted(REGISTERED) == [
        ("order_fulfilment:", "app.orders.fulfilment_projection:FulfilmentActionObserver"),
        ("order_payment:", "app.payments.projection:PaymentOpenObserver"),
        ("order_refund:", "app.payments.refund_projection:RefundActionObserver"),
    ]


def test_no_service_writes_the_domain_state_that_an_observer_owns():
    """El estado de un cobro, un reembolso o un fulfillment que sigue a su acción lo escribe su observador y nadie más
    (los servicios deciden y piden; no escriben el estado «posiblemente enviado»)."""
    possibly_sent = re.compile(
        r"status=(?:PaymentStatus\.OPENING|RefundStatus\.SENDING|FulfillmentStatus\.(?:PURCHASING|SHIPPING))"
    )
    writers = {
        p.relative_to(APP).as_posix() for p in APP.rglob("*.py") if possibly_sent.search(p.read_text(encoding="utf-8"))
    }

    assert writers <= {
        "payments/projection.py",
        "payments/refund_projection.py",
        "orders/fulfilment_projection.py",
    }, sorted(writers)


# --- 3. Las lecturas no escriben
# --------------------------------------------------------------------------------------------

WRITES = re.compile(
    r"\.commit\(|\.add\(|\.flush\(|\bupdate\(|\bdelete\(|\binsert\(|"
    r"\.execute\(\s*(?:update|insert|delete)"
)
API_MODULES = [APP / "api" / "orders.py", APP / "api" / "payments.py", APP / "api" / "fulfillments.py"]


def get_handlers() -> list[tuple[str, str]]:
    """Cada función decorada con `@router.get(...)` en la API de M44: (módulo, código fuente)."""
    handlers: list[tuple[str, str]] = []
    for path in API_MODULES:
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "get"
                ):
                    handlers.append((f"{path.name}:{node.name}", ast.get_source_segment(text, node) or ""))
    return handlers


def test_no_read_route_of_m44_writes_in_its_own_code():
    handlers = get_handlers()
    assert len(handlers) >= 2, "the GET handlers of M44 were not found: the guard would pass for nothing"
    for name, source in handlers:
        assert not WRITES.search(source), f"GET handler {name} writes"


def test_every_read_route_of_orders_is_a_get_and_no_other_verb_reads():
    spec = app.openapi()
    for path, item in spec["paths"].items():
        if not path.startswith("/api/orders"):
            continue
        for method, operation in item.items():
            if method == "get":
                assert "requestBody" not in operation, f"GET {path} takes a body"


# --- 4. Los adaptadores simulados no tienen red
# -----------------------------------------------------------------------------

NETWORK_MODULES = {
    "socket",
    "http",
    "httpx",
    "requests",
    "urllib",
    "urllib3",
    "aiohttp",
    "ssl",
    "ftplib",
    "smtplib",
    "websockets",
}
SIMULATED_ADAPTERS = [
    APP / "payments" / "providers" / "simulated.py",
    APP / "orders" / "simulated_fulfilment.py",
]


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize("path", SIMULATED_ADAPTERS, ids=lambda p: p.name)
def test_a_simulated_adapter_cannot_reach_the_network_because_it_does_not_import_anything_that_can(path):
    assert path.exists()
    assert imported_modules(path) & NETWORK_MODULES == set()


def test_the_m44_domain_code_has_no_network_library_at_all():
    offenders = {
        p.relative_to(APP).as_posix(): sorted(imported_modules(p) & NETWORK_MODULES)
        for p in [*MONEY_CODE, APP / "actions" / "service.py", APP / "idempotency" / "service.py"]
        if p.suffix == ".py" and imported_modules(p) & NETWORK_MODULES
    }
    assert offenders == {}, offenders


# --- 5. Las pruebas no tocan la base real ni cargan el .env
# ------------------------------------------------------------------


def test_the_tests_do_not_read_the_env_file():
    assert Settings.model_config["env_file"] is None, "tests/conftest.py must keep `backend/.env` out of the tests"


def test_no_test_loads_the_env_file_or_names_the_real_supabase_database():
    forbidden = [
        re.compile("load_" + "dotenv"),
        re.compile("dotenv_" + "values"),
        re.compile(r"\b[a-z0-9]{20}\." + "supa" + r"base\.co\b"),  # la referencia de un proyecto real (20 caracteres)
        re.compile(r"db\.[a-z0-9]{20}\." + "supa" + "base"),
        re.compile(r"pooler\." + "supa" + "base"),
        re.compile(r"read_text\([^)]*[\"']\.env[\"']"),
        re.compile(r"open\([^)]*[\"'](?:\.\./)*(?:backend/)?\.env[\"']"),
    ]
    this_file = Path(__file__).resolve()
    offenders = []
    for path in TESTS.rglob("*.py"):
        if path.resolve() == this_file or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(TESTS).as_posix()}: {pattern.pattern}")
    assert offenders == []


def test_the_throwaway_database_of_the_race_tests_can_only_be_a_local_one():
    """Se lee el texto del ayudante (un test unitario no importa de `integration/`): un `DATABASE_URL` que no sea local
    hace que la prueba se **omita**, nunca que cree y borre bases en otra parte."""
    source = (TESTS / "integration" / "pg_test_support.py").read_text(encoding="utf-8")

    assert re.search(r'LOCAL_HOSTS\s*=\s*\{"localhost", "127\.0\.0\.1", "::1"\}', source)
    assert "url.host not in LOCAL_HOSTS" in source and "pytest.skip" in source


# --- 6. Ningún cuerpo bruto de webhook se guarda
# ----------------------------------------------------------------------------


def test_no_column_can_hold_a_raw_webhook_body():
    events = Base.metadata.tables["payment_events"]
    for column in events.columns:
        assert not isinstance(column.type, (Text,)), f"payment_events.{column.name} is a free text column"
        assert not any(word in column.name for word in ("body", "raw", "payload_text", "content")), column.name
        if isinstance(column.type, String):
            assert column.type.length is not None and column.type.length <= 500, (
                f"payment_events.{column.name} unbounded"
            )
    assert "payload_hash" in events.columns and events.columns["payload_hash"].type.length == 64, "only its SHA-256"
