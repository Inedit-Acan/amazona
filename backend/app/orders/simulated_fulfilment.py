"""El proveedor de fulfillment simulado (Milestone 44, ADR 0028 §6): no compra ni envía nada fuera de AMAZONA.

Cumple el contrato completo de un adaptador con efecto —idempotente, consultable, con coste declarado— para que el
ciclo de vida de una compra y de un envío sea exactamente el que tendrá con un proveedor real:

- la **compra** cuesta lo que suman las líneas, y es desconocida si falta el coste de alguna (no se supone cero);
- el **envío** cuesta cero **declarado y simulado**: no hay transportista ni tarifa.
"""

import hashlib
import threading
from collections.abc import Sequence

from app.actions.contract import ActionRequest, ActionResponse, ProviderRejectedError
from app.gates.action_gate import ActionCost
from app.money.money import Money, total
from app.money.serialization import legacy_float
from app.orders.fulfilment_port import (
    OPERATION_PURCHASE,
    OPERATION_SHIP,
    PHASE_PURCHASE,
    PHASE_SHIP,
    PHASES,
    FulfilmentLine,
    FulfilmentProviderCapabilities,
)

PROVIDER_NAME = "simulated-fulfilment"


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class SimulatedFulfilmentAdapter:
    name = PROVIDER_NAME
    supports_idempotency = True
    capabilities = FulfilmentProviderCapabilities(
        name=PROVIDER_NAME,
        supports_idempotency=True,
        supports_lookup=True,
        phases=frozenset(PHASES),
    )

    #: Su `lookup` es la memoria de **este proceso** (`_shared_operations`): no vale entre procesos, así que **no es
    #: autoritativo**
    #: (ADR 0029 §7). Un worker nunca cerrará con ella una acción que la API «ejecutó».
    lookup_is_authoritative = False

    _shared_operations: dict[str, ActionResponse] = {}
    _shared_lock = threading.Lock()

    def __init__(self, *, operations: dict[str, ActionResponse] | None = None) -> None:
        self._operations = operations if operations is not None else self._shared_operations

    def execute(self, request: ActionRequest) -> ActionResponse:
        if request.operation not in (OPERATION_PURCHASE, OPERATION_SHIP):
            raise ProviderRejectedError(f"{PROVIDER_NAME} does not support {request.operation}")
        if not request.idempotency_key:
            raise ProviderRejectedError("this provider needs the idempotency key of the operation")
        prefix = "simpo_" if request.operation == OPERATION_PURCHASE else "simtrk_"
        with self._shared_lock:
            existing = self._operations.get(request.idempotency_key)
            if existing is not None:
                return existing
            response = ActionResponse(
                reference=f"{prefix}{_digest(request.idempotency_key)}",
                detail={"simulated": True, "operation": request.operation},
            )
            self._operations[request.idempotency_key] = response
            return response

    def lookup(self, idempotency_key: str) -> ActionResponse | None:
        with self._shared_lock:
            return self._operations.get(idempotency_key)

    def effect_count(self) -> int:
        with self._shared_lock:
            return len(self._operations)

    def quote_cost(self, *, phase: str, lines: Sequence[FulfilmentLine], currency: str) -> ActionCost:
        if phase == PHASE_SHIP:
            return ActionCost.zero("simulated")
        if phase != PHASE_PURCHASE:
            return ActionCost.unknown()
        if not lines or any(line.unit_cost is None for line in lines):
            return ActionCost.unknown()
        parts: list[Money] = []
        for line in lines:
            assert line.unit_cost is not None  # comprobado arriba
            if line.unit_cost.currency != currency:
                return ActionCost.unknown()  # otra moneda sin convertir: no se inventa un tipo de cambio
            parts.append(line.unit_cost * line.quantity)
        amount = legacy_float(total(parts, currency=currency))
        if amount is None or amount <= 0:
            return ActionCost.zero("order_line_cost")
        return ActionCost.known(amount, "order_line_cost")
