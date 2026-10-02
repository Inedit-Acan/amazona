"""La frontera del dinero cobrado, hecha cumplir por pruebas (Milestone 44, ADR 0028 §1).

Una convención se olvida; una prueba que recorre el código, no. Tres cosas, y las tres son la misma promesa: **un pago
solo se confirma por un evento verificado, y solo lo aplica `PaymentService`**.

1. Solo un proveedor puede acreditar que verificó un evento (la ficha `PROOF`).
2. Solo `PaymentService` y el observador de `payment.open` escriben el estado de un cobro, y solo `PaymentService`
   pone un pedido en `PAID`.
3. Nada de lo que atiende a un cliente, a un navegador o a la consola construye un evento de pago ni lo aplica por su
   cuenta: todo pasa por `PaymentIngress`.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def python_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def relative(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def files_matching(pattern: str) -> set[str]:
    regex = re.compile(pattern)
    return {relative(p) for p in python_files() if regex.search(p.read_text(encoding="utf-8"))}


def test_only_a_provider_can_import_the_proof_that_an_event_was_verified():
    importers = files_matching(
        r"from app\.payments\.verification import[^\n]*\bPROOF\b|import app\.payments\.verification"
    )

    allowed = {"payments/port.py"} | {relative(p) for p in (APP / "payments" / "providers").glob("*.py")}
    assert importers <= allowed, f"{sorted(importers - allowed)} can mint a verified event without verifying anything"
    assert "payments/providers/simulated.py" in importers


def test_only_the_payment_service_and_the_open_observer_write_the_state_of_a_payment():
    writers = files_matching(r"update\(Payment\)")

    assert writers == {"payments/service.py", "payments/projection.py", "payments/ledger.py"}, (
        "the state of a payment is written by the PaymentService and the observer of `payment.open`; "
        "the refund arithmetic lives in payments/ledger.py and never touches the status"
    )
    ledger = (APP / "payments" / "ledger.py").read_text(encoding="utf-8")
    assert "status=" not in ledger.replace("Payment.status.in_", ""), "the ledger moves amounts, not states"


def test_only_the_payment_service_marks_an_order_as_paid():
    marks = files_matching(r"OrderStatus\.PAID")

    assert marks == {"orders/domain.py", "payments/service.py", "orders/attention.py"}, sorted(marks)
    service = (APP / "payments" / "service.py").read_text(encoding="utf-8")
    assert "paid_at" in service
    others = [p for p in python_files() if relative(p) != "payments/service.py"]
    assert not [
        relative(p)
        for p in others
        if re.search(r"paid_at\s*=|\bpaid_at=", p.read_text(encoding="utf-8")) and relative(p) not in {"api/orders.py"}
    ], "no other module sets paid_at"


def test_a_payment_event_is_built_only_by_the_door_and_never_by_a_route_or_the_console():
    builders = files_matching(r"(?<!class )\bPaymentEvent\(")

    assert builders == {"payments/ingress.py"}, f"{sorted(builders)} build payment events outside PaymentIngress"


def test_nothing_but_the_door_and_the_console_applies_an_event():
    appliers = files_matching(r"\.apply\(")
    applies_payment_events = {
        name
        for name in appliers
        if re.search(r"PaymentService\([^)]*\)\.apply\(", (APP / name).read_text(encoding="utf-8"))
    }

    assert applies_payment_events <= {"payments/ingress.py", "cli.py"}, sorted(applies_payment_events)


def test_no_route_accepts_a_payment_state_in_its_request_models():
    for name in ("api/orders.py", "api/payments.py"):
        source = (APP / name).read_text(encoding="utf-8")
        for forbidden in ("captured_amount: str", "status: str = ", "paid: bool", "is_paid", "mark_paid"):
            assert forbidden not in source.split("class OrderCreate")[-1].split("class MoneyOut")[0], (name, forbidden)


def test_the_cli_does_not_edit_orders_or_payments_directly():
    cli = (APP / "cli.py").read_text(encoding="utf-8")

    assert "update(Order" not in cli and "update(Payment" not in cli
    assert ".status =" not in cli.split("def simulate_payment")[1].split("def build_parser")[0]
    simulate = cli.split("def simulate_payment")[1].split("def reconcile_payment_events")[0]
    assert "PaymentIngress" in simulate and "simulate_event" in simulate, "a simulated event goes through the same door"
