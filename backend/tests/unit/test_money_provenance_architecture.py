"""Nada en la ruta del dinero deduce el origen de un cobro: lo declara el proveedor (Milestone 46, ADR 0031).

El origen (`mock`, `sandbox`, `real`) separa dinero simulado de dinero real. La convención «no lo deduzcas» se olvida;
una prueba que recorre el árbol sintáctico, no. Esta guarda impide que `orders/`, `payments/`, `revenue/` y
`reconciliation/` **clasifiquen dinero** con cualquier cosa que no sea el `provider_kind` que el proveedor declara y que
ya está guardado en el cobro, el evento o la entrada:

- **`signal`**: `ProviderBinding.is_simulated` (colapsa `sandbox` en «no simulado»), `ProviderRegistry.kind_for`,
  `binding_for` y `bindings` (leen `Settings`, no al adaptador), `Settings.operating_in_simulation`,
  `payments_provider` y `environment`, y el `is_simulated` del pedido (contexto histórico del pedido, ADR 0031 §12).
- **`kind_member` / `kind_build` / `kind_literal`**: nombrar `ProviderKind.MOCK` (u otro), construir un `ProviderKind` o
  escribir `"mock"`, `"sandbox"`, `"real"`, `"simulated-payments"`. Solo el puerto (`payments/port.py`) y los
  adaptadores (`payments/providers/`) pueden declarar o validar un origen.
- **`name_compare` / `name_call`**: comparar el nombre de un proveedor con una constante o mirar su prefijo.
- **`kind_value` / `kind_assign`**: dar a `provider_kind=` algo que no sea el origen del proveedor, del cobro o de la
  captura; o asignar a `.provider_kind` (es inmutable).
- **`adapter_import`**: importar un adaptador concreto.

Las excepciones están **nombradas una a una con su motivo** (`ALLOWED`); una excepción que ya no se usa falla (la lista
solo puede menguar). El propio escáner se prueba con fragmentos que debe rechazar y con otros que debe dejar pasar: una
guarda que no ve nada pasa siempre.

La prueba dinámica complementaria (el origen no cambia aunque `Order.is_simulated`, `ProviderBinding.is_simulated` o los
ajustes digan otra cosa) está en `tests/integration/test_origin_inference_poison.py`.
"""

import ast
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.integrations.ports import ProviderKind
from app.integrations.registry import ProviderBinding, ProviderRegistry

APP = Path(__file__).resolve().parents[2] / "app"
SCOPE = ("orders", "payments", "revenue", "reconciliation")

#: Lo que lee o construye una señal de «es simulado», de entorno o de configuración del proveedor.
SIGNAL_ATTRIBUTES = {
    "is_simulated",
    "operating_in_simulation",
    "all_providers_simulated",
    "payments_provider",
    "environment",
    "kind_for",
    "binding_for",
    "bindings",
}
KIND_STRINGS = {"mock", "sandbox", "real", "composite", "simulated-payments"}
STRING_METHODS = {"startswith", "endswith", "lower", "upper", "split", "removeprefix", "removesuffix", "find"}
#: `provider.name`, `self._provider.name`, `binding.name`, `candidate.name`, `Payment.provider`, `customer_ref`.
NAME_CHAIN = re.compile(r"((provider|binding|candidate|adapter)\w*(\.\w+)*\.name|(^|\.)provider|(^|\.)customer_ref)$")

#: Declaran o validan un origen: el puerto y los adaptadores (ADR 0031 §4).
KIND_DECLARING = ("payments/port.py", "payments/providers/")

Violation = tuple[str, int, str]  # (regla, línea, detalle)


def docstring_ids(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def declares_kind(relative: str) -> bool:
    return any(relative == prefix or relative.startswith(prefix) for prefix in KIND_DECLARING)


def is_str_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, (ast.Tuple, ast.Set, ast.List)):
        return bool(node.elts) and all(is_str_constant(item) for item in node.elts)
    return False


def allowed_kind_value(value: ast.AST) -> bool:
    """El origen de un `provider_kind=`: el atributo `provider_kind` de otro hecho, o el origen que el proveedor declaró
    (`provider_kind`, `provider_kind.value`)."""
    if isinstance(value, ast.Name):
        return value.id == "provider_kind"
    if isinstance(value, ast.Attribute):
        if value.attr == "provider_kind":
            return True
        return value.attr == "value" and isinstance(value.value, ast.Name) and value.value.id == "provider_kind"
    return False


def scan(source: str, relative: str) -> list[Violation]:
    tree = ast.parse(source)
    docs = docstring_ids(tree)
    found: list[Violation] = []
    for node in ast.walk(tree):
        # --- señales de «es simulado», de entorno y de configuración
        if isinstance(node, ast.Attribute) and node.attr in SIGNAL_ATTRIBUTES:
            found.append(("signal", node.lineno, node.attr))
        elif isinstance(node, ast.keyword) and node.arg == "is_simulated":
            found.append(("signal", node.value.lineno, "is_simulated="))
        elif isinstance(node, ast.Name) and node.id == "ProviderBinding":
            found.append(("signal", node.lineno, "ProviderBinding"))
        elif isinstance(node, ast.alias) and node.name == "ProviderBinding":
            found.append(("signal", getattr(node, "lineno", 0), "import ProviderBinding"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "hasattr", "setattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in SIGNAL_ATTRIBUTES | {"provider_kind"}
        ):
            found.append(("signal", node.lineno, f"{node.func.id}({node.args[1].value!r})"))

        # --- el origen solo se declara en el puerto y en los adaptadores
        if not declares_kind(relative):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ProviderKind":
                found.append(("kind_member", node.lineno, f"ProviderKind.{node.attr}"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ProviderKind":
                found.append(("kind_build", node.lineno, "ProviderKind(...)"))
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
                and node.value in KIND_STRINGS
            ):
                found.append(("kind_literal", node.lineno, node.value))

        # --- el nombre del proveedor no clasifica
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            named = [ast.unparse(side) for side in sides if NAME_CHAIN.search(ast.unparse(side).lower())]
            if named and any(is_str_constant(side) for side in sides):
                found.append(("name_compare", node.lineno, named[0]))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHODS:
            receiver = ast.unparse(node.func.value)
            if NAME_CHAIN.search(receiver.lower()):
                found.append(("name_call", node.lineno, f"{receiver}.{node.func.attr}"))

        # --- el valor de `provider_kind` y su inmutabilidad
        if isinstance(node, ast.keyword) and node.arg == "provider_kind" and not allowed_kind_value(node.value):
            found.append(("kind_value", node.value.lineno, ast.unparse(node.value)))
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "provider_kind":
                found.append(("kind_assign", node.lineno, ast.unparse(target)))

        # --- ningún adaptador concreto
        if (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("app.payments.providers")
            and not relative.startswith("payments/providers/")
        ):
            found.append(("adapter_import", node.lineno, node.module or ""))
    return sorted(set(found), key=lambda item: (item[1], item[0], item[2]))


#: Las excepciones, una a una: (fichero, regla, detalle) → por qué no es clasificar dinero.
ALLOWED: dict[tuple[str, str, str], str] = {
    ("orders/service.py", "signal", "operating_in_simulation"): (
        "al crear el pedido se anota si el despliegue era una simulación: contexto histórico del pedido, no "
        "procedencia del dinero (ADR 0031 §12)"
    ),
    ("orders/service.py", "signal", "is_simulated="): (
        "es esa misma anotación, escrita en `Order.is_simulated` al crear el pedido (ADR 0031 §12)"
    ),
    ("orders/gate_inputs.py", "signal", "operating_in_simulation"): (
        "la puerta legal: fuera de una simulación un producto sin análisis legal no se vende solo; no clasifica ningún "
        "importe"
    ),
    ("reconciliation/config_check.py", "kind_member", "ProviderKind.MOCK"): (
        "la comprobación de arranque decide qué adaptadores de escritura validar frente al techo de la llamada "
        "externa; lee la configuración para validar, no para clasificar ningún importe"
    ),
    ("orders/domain.py", "name_call", "customer_ref.startswith"): (
        "valida que la referencia del cliente lleve el prefijo `sim_` solo en una simulación (el CHECK del pedido); no "
        "toca ningún cobro"
    ),
}


def repository_files() -> list[Path]:
    return sorted(p for scope in SCOPE for p in (APP / scope).rglob("*.py") if "__pycache__" not in p.parts)


def repository_violations() -> dict[tuple[str, str, str], list[int]]:
    found: dict[tuple[str, str, str], list[int]] = {}
    for path in repository_files():
        relative = path.relative_to(APP).as_posix()
        for rule, line, detail in scan(path.read_text(encoding="utf-8"), relative):
            found.setdefault((relative, rule, detail), []).append(line)
    return found


# --- 1. El código real ------------------------------------------------------------------------------------------------


def test_the_scan_covers_the_files_where_the_origin_travels():
    relatives = {p.relative_to(APP).as_posix() for p in repository_files()}
    assert {
        "revenue/ledger.py",
        "revenue/check.py",
        "payments/service.py",
        "payments/ingress.py",
        "payments/port.py",
        "payments/providers/simulated.py",
        "orders/payment_attempts.py",
        "orders/refunds.py",
        "orders/service.py",
        "reconciliation/report.py",
    } <= relatives, "a directory moved: the guard would pass for nothing"


def test_no_money_code_infers_the_origin_of_a_payment_from_anything_but_the_provider_that_declared_it():
    unknown = {key: lines for key, lines in repository_violations().items() if key not in ALLOWED}
    assert not unknown, (
        "the origin of money (mock/sandbox/real) is declared by the provider and read from what is persisted; it is "
        f"never inferred (ADR 0031 §4, §12): {unknown}"
    )


def test_every_named_exception_is_still_needed_the_list_can_only_shrink():
    found = repository_violations()
    stale = [key for key in ALLOWED if key not in found]
    assert not stale, f"exceptions that no longer exist, remove them: {stale}"


def test_every_exception_says_why_it_is_not_classifying_money():
    assert all(len(reason) > 40 for reason in ALLOWED.values())


def test_the_names_the_guard_looks_for_still_exist_so_it_cannot_rot_into_a_no_op():
    assert hasattr(ProviderBinding, "is_simulated")
    for method in ("kind_for", "binding_for", "bindings", "resolve"):
        assert hasattr(ProviderRegistry, method), method
    assert {"MOCK", "SANDBOX", "REAL", "COMPOSITE"} <= set(ProviderKind.__members__)
    assert {m.value for m in ProviderKind if m.name in {"MOCK", "SANDBOX", "REAL", "COMPOSITE"}} == {
        "mock",
        "sandbox",
        "real",
        "composite",
    }
    settings_names = set(Settings.model_fields) | {n for n in dir(Settings) if not n.startswith("_")}
    for name in SIGNAL_ATTRIBUTES - {"is_simulated", "kind_for", "binding_for", "bindings"}:
        assert name in settings_names, f"Settings no longer has {name}"


# --- 2. El escáner se prueba a sí mismo ------------------------------------------------------------------------------

MUST_BE_REJECTED = [
    ("signal", "x = binding.is_simulated"),
    ("signal", "x = registry.binding_for(domain).kind"),
    ("signal", "x = ProviderRegistry(s).kind_for(domain)"),
    ("signal", "x = ProviderRegistry(s).bindings()"),
    ("signal", "x = settings.operating_in_simulation"),
    ("signal", "x = self._settings.payments_provider"),
    ("signal", "x = settings.environment"),
    ("signal", "x = order.is_simulated"),
    ("signal", "Order(is_simulated=True)"),
    ("signal", "x = getattr(binding, 'is_simulated')"),
    ("signal", "from app.integrations.registry import ProviderBinding"),
    ("kind_member", "x = ProviderKind.MOCK"),
    ("kind_member", "x = a == ProviderKind.REAL"),
    ("kind_build", "x = ProviderKind(value)"),
    ("kind_literal", "x = 'mock'"),
    ("kind_literal", "kind = 'sandbox' if flag else 'real'"),
    ("kind_literal", "x = 'simulated-payments'"),
    ("name_compare", "ok = provider.name == 'simulated-payments'"),
    ("name_compare", "ok = self._provider.name in ('a', 'b')"),
    ("name_compare", "ok = 'sim' == binding.name"),
    ("name_compare", "ok = Payment.provider == 'simulated-payments'"),
    ("name_call", "ok = provider.name.startswith('sim')"),
    ("name_call", "ok = customer_ref.startswith('sim_')"),
    ("name_call", "ok = candidate.name.lower()"),
    ("kind_value", "Payment(provider_kind='mock')"),
    ("kind_value", "Payment(provider_kind=ProviderKind.MOCK.value)"),
    ("kind_value", "Payment(provider_kind='mock' if order.is_simulated else 'real')"),
    ("kind_value", "RevenueLedgerEntry(provider_kind=settings.payments_provider.value)"),
    ("kind_value", "PaymentEvent(provider_kind=provider.name)"),
    ("kind_assign", "payment.provider_kind = 'real'"),
    ("kind_assign", "event.provider_kind = payment.provider_kind"),
    ("adapter_import", "from app.payments.providers.simulated import SimulatedPaymentProvider"),
]

MUST_PASS = [
    "Payment(provider_kind=provider_kind.value)",
    "RevenueLedgerEntry(provider_kind=payment.provider_kind)",
    "RevenueLedgerEntry(provider_kind=capture.provider_kind)",
    "PaymentEvent(provider_kind=provider_kind)",
    "ok = event.provider_kind != payment.provider_kind",
    "ok = Payment.provider == event.provider",
    "ok = candidate.name != name",  # enrutar una URL por el nombre del proveedor no es clasificar: sin constante
    "ok = dialect.name == 'postgresql'",
    "ok = headers.get(name.lower())",
    "x = provider_kind.value",
    "def f():\n    '''mock, sandbox and real are the origins of the money'''\n    return 1",
    "x = ProviderRegistry(s).resolve(domain)",
]


@pytest.mark.parametrize(("rule", "snippet"), MUST_BE_REJECTED, ids=lambda v: v if isinstance(v, str) else None)
def test_the_scanner_rejects_what_it_exists_to_reject(rule: str, snippet: str):
    assert rule in {r for r, _, _ in scan(snippet, "payments/service.py")}, f"{rule} not found in {snippet!r}"


@pytest.mark.parametrize("snippet", MUST_PASS)
def test_the_scanner_lets_the_legitimate_code_through(snippet: str):
    assert scan(snippet, "payments/service.py") == []


def test_only_the_port_and_the_adapters_may_declare_or_validate_an_origin():
    snippet = "x = ProviderKind.MOCK\ny = ProviderKind(value)\nz = 'mock'"
    assert {r for r, _, _ in scan(snippet, "payments/service.py")} == {"kind_member", "kind_build", "kind_literal"}
    assert scan(snippet, "payments/port.py") == []
    assert scan(snippet, "payments/providers/simulated.py") == []
    assert {r for r, _, _ in scan(snippet, "payments/providers_other.py")} == {
        "kind_member",
        "kind_build",
        "kind_literal",
    }, "only the `providers/` directory and `port.py` are exempt, not a file that merely starts the same"
    assert {r for r, _, _ in scan(snippet, "revenue/ledger.py")} == {"kind_member", "kind_build", "kind_literal"}


def test_an_adapter_may_declare_its_origin_but_not_assign_it_to_a_fact():
    assert scan("class A:\n    kind = ProviderKind.SANDBOX", "payments/providers/sandbox.py") == []
    assert [r for r, _, _ in scan("p.provider_kind = ProviderKind.SANDBOX", "payments/providers/sandbox.py")] == [
        "kind_assign"
    ], "a persisted fact is immutable, and the adapter is not exempt from that"


def test_a_docstring_may_name_the_origins_a_string_value_may_not():
    assert scan('"""mock real sandbox"""\nx = 1', "revenue/ledger.py") == []
    assert [r for r, _, _ in scan("x = 'real'", "revenue/ledger.py")] == ["kind_literal"]
