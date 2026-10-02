"""Qué operaciones externas declara soportar cada adaptador, y bajo qué condiciones (Milestone 44, ADR 0028 §7).

## No es otra fuente de verdad de derechos

Son dos preguntas distintas y cada una tiene su sitio:

- `usage_rights` responde **qué podemos hacer con los datos** de una fuente: guardarlos, derivar métricas,
  redistribuirlos (ADR 0015);
- esto responde **qué operaciones externas declara soportar** un adaptador de acciones y bajo qué condiciones:
  si sus efectos son reales o simulados y cómo declara lo que cuesta cada una.

Una política no dice nada de qué se puede hacer con un dato, y una entrada de derechos no dice qué operaciones
admite un adaptador. Un proveedor real de pagos necesitará **las dos**: sus condiciones sobre los datos que
devuelve (`usage_rights`) y las operaciones que declara (esto).

## La regla de siempre: lo que no se sabe, no se permite

Un proveedor sin política, o una operación que su política no declara, se **deniega**. Igual que un derecho
`UNKNOWN` pesa como `DENIED`, una operación no declarada no es una operación permitida. Un adaptador real nuevo
no puede ejecutar nada hasta que alguien escriba, con su fuente y su fecha, qué dice soportar.
"""

import datetime
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.config import Settings
from app.core.errors import ConflictError


class CostModel(StrEnum):
    """Cómo declara el adaptador lo que cuesta una operación."""

    #: Cero declarado y simulado: no hay tarifa porque no hay efecto.
    ZERO_SIMULATED = "zero_simulated"
    #: Lo calcula el servicio de dominio a partir de datos conocidos (las líneas de un pedido).
    FROM_ORDER_LINES = "from_order_lines"
    #: El adaptador lo cotiza (`quote_cost`); si no sabe, `UNKNOWN`.
    QUOTED = "quoted"
    #: La operación no tiene un coste propio para nosotros (abrir un cobro o devolver dinero cobrado).
    NOT_APPLICABLE = "not_applicable"


class OperationNotPermittedError(ConflictError):
    """El adaptador no declara esta operación, o sus efectos no valen en este entorno."""


@dataclass(frozen=True)
class OperationPolicy:
    operation: str
    #: Si la operación toca algo fuera de AMAZONA de verdad. `False` = simulada.
    real_effects: bool
    cost_model: CostModel
    note: str = ""


@dataclass(frozen=True)
class ProviderOperatingPolicy:
    """Lo que se leyó de lo que el adaptador declara, y cuándo."""

    provider: str
    #: Dónde se declara. Sin esto, la política es una opinión.
    source: str
    verified_on: datetime.date
    operations: dict[str, OperationPolicy] = field(default_factory=dict)

    def declares(self, operation: str) -> bool:
        return operation in self.operations


_SIMULATED_PAYMENTS = ProviderOperatingPolicy(
    provider="simulated-payments",
    source="app/payments/providers/simulated.py — el simulador del repositorio",
    verified_on=datetime.date(2026, 10, 2),
    operations={
        "payment.open": OperationPolicy("payment.open", False, CostModel.NOT_APPLICABLE, "abrir un cobro simulado"),
        "payment.refund": OperationPolicy(
            "payment.refund", False, CostModel.NOT_APPLICABLE, "devolver un cobro simulado"
        ),
    },
)

_SIMULATED_FULFILMENT = ProviderOperatingPolicy(
    provider="simulated-fulfilment",
    source="app/orders/simulated_fulfilment.py — el simulador del repositorio",
    verified_on=datetime.date(2026, 10, 2),
    operations={
        "fulfillment.purchase": OperationPolicy(
            "fulfillment.purchase", False, CostModel.FROM_ORDER_LINES, "la compra suma el coste de las líneas"
        ),
        "fulfillment.ship": OperationPolicy(
            "fulfillment.ship", False, CostModel.ZERO_SIMULATED, "sin transportista: cero declarado y simulado"
        ),
    },
)

OPERATING_POLICIES: dict[str, ProviderOperatingPolicy] = {
    _SIMULATED_PAYMENTS.provider: _SIMULATED_PAYMENTS,
    _SIMULATED_FULFILMENT.provider: _SIMULATED_FULFILMENT,
}

#: Para un proveedor del que nadie ha escrito nada: no declara ninguna operación.
UNREGISTERED = ProviderOperatingPolicy(
    provider="<unregistered>",
    source="nadie ha escrito qué operaciones declara este adaptador",
    verified_on=datetime.date(2026, 10, 2),
)


def policy_for(provider: str) -> ProviderOperatingPolicy:
    return OPERATING_POLICIES.get(provider, UNREGISTERED)


def require_operation(provider: str, operation: str, settings: Settings) -> OperationPolicy:
    """La política de esta operación, o `OperationNotPermittedError`.

    Se deniega si el proveedor no está registrado, si no declara la operación, o si es un adaptador simulado en un
    entorno que no admite simulación (staging y production, donde los efectos tienen que ser reales)."""
    policy = policy_for(provider)
    declared = policy.operations.get(operation)
    if declared is None:
        raise OperationNotPermittedError(
            f"{provider} does not declare {operation}: an operation nobody wrote down is not permitted"
        )
    if not declared.real_effects and not settings.allows_simulated_providers:
        raise OperationNotPermittedError(
            f"{provider} is simulated and {settings.environment} does not accept simulated effects"
        )
    return declared
