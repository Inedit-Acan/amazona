"""El vocabulario del núcleo de pedidos (Milestone 44, ADR 0028): estados, transiciones y reglas de forma.

Los estados y las transiciones están aquí, en un solo sitio, y las pruebas recorren la tabla entera: una
transición que no figura es una transición prohibida.
"""

import re
from decimal import Decimal
from enum import StrEnum

from app.core.errors import ValidationError
from app.money.money import Money

#: La referencia opaca de un cliente. Nunca un dato personal: ni un email (lleva `@`), ni un nombre con espacios.
CUSTOMER_REF_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
#: En una simulación, toda referencia de cliente empieza por esto; fuera de ella, ninguna puede hacerlo.
SIMULATION_PREFIX = "sim_"

MAX_LINES_PER_ORDER = 50
MAX_QUANTITY_PER_LINE = 10_000

_CENT = Decimal("0.01")


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


#: Las únicas transiciones válidas de un pedido. `AWAITING_PAYMENT → PAID` solo la hace `PaymentService`,
#: tras un evento de pago verificado; `PAID → COMPLETED`, el fulfillment cuando todo está entregado.
ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.AWAITING_PAYMENT: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.COMPLETED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ORDER_TRANSITIONS[current]


def validate_customer_ref(customer_ref: str, *, simulated: bool) -> str:
    """La referencia de cliente, o `ValidationError`. Es lo que mantiene los datos personales fuera del modelo."""
    if not CUSTOMER_REF_PATTERN.fullmatch(customer_ref or ""):
        raise ValidationError(
            "customer_ref must be an opaque reference of 1-64 characters from A-Z a-z 0-9 . _ : - : "
            "never a name, an email or any other personal data"
        )
    starts_simulated = customer_ref.startswith(SIMULATION_PREFIX)
    if simulated and not starts_simulated:
        raise ValidationError(f"in a simulation every customer_ref starts with {SIMULATION_PREFIX!r}")
    if not simulated and starts_simulated:
        raise ValidationError(f"a customer_ref starting with {SIMULATION_PREFIX!r} is reserved for simulations")
    return customer_ref


def require_cents(amount: Money, label: str) -> Money:
    """Los cobros, los reembolsos y los precios se limitan a céntimos: más decimales se redondearían a otra cosa de
    lo que se escribió, y el proveedor de pagos trabaja en céntimos."""
    if amount.amount != amount.amount.quantize(_CENT):
        raise ValidationError(f"{label} must be a whole number of cents, got {amount.amount}")
    return amount
