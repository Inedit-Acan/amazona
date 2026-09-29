"""Costes de canal de fixture. Sin red (Milestone 40).

En un marketplace la comisión se cobra y la pasarela va dentro. En una **web
propia** no hay comisión y la pasarela la pagamos nosotros: un 2,9 % del precio
más unos céntimos, que sobre un margen del 20 % es una séptima parte del margen.
Es un coste **material**, así que un análisis que no lo conoce no está completo
— y eso es lo que el Milestone 40 declara en vez de callar.

Lo que este módulo hace es dar ese coste **para la cadena de demostración**, con
procedencia `simulated`, y solo donde la ADR 0008 admite datos simulados. En un
entorno que no los admite no se monta: allí el coste de pasarela hay que
declararlo, o el análisis es no evaluable. Que es lo correcto.

El 2,9 % + 0,25 € es la tarifa de referencia que la pantalla de Economía ya
usaba como supuesto de demostración desde el Milestone 22. **No es una tarifa
contratada con nadie.**
"""

from dataclasses import dataclass
from decimal import Decimal

SOURCE = "fixtures:mock-channel-costs"


@dataclass(frozen=True)
class PaymentFee:
    """Lo que cuesta cobrar. Fracción del precio más una parte fija."""

    percent_of_price: Decimal
    fixed_per_transaction: Decimal


#: Por tipo de canal. Los marketplaces no aparecen: allí el cobro va dentro de
#: la comisión, y ponerlo aquí además lo contaría dos veces.
_PAYMENT_FEES: dict[str, PaymentFee] = {
    "own_web": PaymentFee(percent_of_price=Decimal("0.029"), fixed_per_transaction=Decimal("0.25")),
}


class MockChannelCostDirectory:
    """Costes de canal de fixture, deterministas y marcados como simulados."""

    name = "mock-channel-costs"

    def payment_fee_for(self, *, channel_kind: str) -> PaymentFee | None:
        return _PAYMENT_FEES.get(channel_kind)
