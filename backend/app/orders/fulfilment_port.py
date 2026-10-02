"""El puerto de un proveedor de fulfillment (Milestone 44, ADR 0028 §6 y §7).

Comprar al proveedor y mandar el envío son dos operaciones externas distintas, cada una con su `ExternalAction`.
Un adaptador real las cumplirá con su API; el simulado no hace nada fuera de AMAZONA.

El contrato añade una cosa al de cualquier acción externa: **declara lo que cuesta cada operación**
(`quote_cost`). Un coste puede ser cero declarado, conocido o desconocido, y el desconocido nunca es cero: ni el
gate lo deja pasar ni un adaptador real puede ejecutar un gasto a ciegas. No se construyen tarifas de transporte;
solo se impide que el contrato las deje fuera.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.actions.contract import ExternalActionAdapter
from app.money.money import Money

if TYPE_CHECKING:
    # Solo para tipos: `app.integrations.ports` importa este módulo y `action_gate` importa la configuración,
    # que a su vez importa los puertos.
    from app.gates.action_gate import ActionCost

PHASE_PURCHASE = "purchase"
PHASE_SHIP = "ship"
PHASES = (PHASE_PURCHASE, PHASE_SHIP)

OPERATION_PURCHASE = "fulfillment.purchase"
OPERATION_SHIP = "fulfillment.ship"
OPERATION_FOR_PHASE = {PHASE_PURCHASE: OPERATION_PURCHASE, PHASE_SHIP: OPERATION_SHIP}


@dataclass(frozen=True)
class FulfilmentProviderCapabilities:
    """Lo que el adaptador **declara** poder hacer."""

    name: str
    supports_idempotency: bool
    supports_lookup: bool
    #: Las fases que sabe ejecutar (`purchase`, `ship`).
    phases: frozenset[str]


@dataclass(frozen=True)
class FulfilmentLine:
    """Una parte de una línea del pedido que se compra o se envía: lo que el adaptador necesita saber para
    declarar un coste. El coste unitario es `None` cuando no se conoce (y entonces **no es cero**)."""

    order_item_id: str
    line_number: int
    product_id: str
    quantity: int
    unit_cost: Money | None


@runtime_checkable
class FulfilmentProvider(ExternalActionAdapter, Protocol):
    capabilities: FulfilmentProviderCapabilities

    def quote_cost(self, *, phase: str, lines: Sequence[FulfilmentLine], currency: str) -> "ActionCost":
        """Lo que cuesta esta fase para estas líneas. `ActionCost.unknown()` si no se sabe: el adaptador no
        inventa un coste."""
        ...
