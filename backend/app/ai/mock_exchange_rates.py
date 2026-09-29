"""Tipos de cambio de fixture. Sin red (Milestone 40).

Existe por una consecuencia concreta del Milestone 39: el directorio de
proveedores de fixture cotiza en dólares —es lo que hace un directorio
asiático— y el sistema razona márgenes en euros. Sin tasa, **todo** análisis
sobre datos de demostración es no evaluable, que es literalmente correcto y deja
la cadena de demostración sin poder llegar al final.

La respuesta no es inventar una tasa y llamarla dato: es dar una tasa de fixture
que **dice que es un fixture**, y dejar que la regla de la ADR 0008 decida dónde
se puede usar. En un entorno que no admite datos simulados esta fuente no se
monta, así que producción sigue exigiendo una tasa declarada de verdad — o
declarando el análisis no evaluable, que es lo que debe pasar.

Los números son de septiembre de 2026 y **no son una cotización**: son una
referencia plausible para que una cadena inventada produzca un número
inventado coherente.
"""

import datetime
from decimal import Decimal

from app.money.rates import ExchangeRate
from app.sourcing.provenance import SupplierFactProvenance

SOURCE = "fixtures:mock-exchange-rates"

#: `(base, quote) -> tasa`. `1 base = rate quote`.
_RATES: dict[tuple[str, str], Decimal] = {
    ("USD", "EUR"): Decimal("0.92"),
    ("GBP", "EUR"): Decimal("1.17"),
    ("CNY", "EUR"): Decimal("0.13"),
    ("PLN", "EUR"): Decimal("0.23"),
    ("VND", "EUR"): Decimal("0.000035"),
    ("MXN", "EUR"): Decimal("0.050"),
    ("HKD", "EUR"): Decimal("0.118"),
}


class MockExchangeRateProvider:
    """Tasas de fixture, deterministas y marcadas como simuladas."""

    name = "mock-exchange-rates"

    def rate_for(
        self, *, base: str, quote: str, on: datetime.date
    ) -> ExchangeRate | None:
        rate = _RATES.get((base.strip().upper(), quote.strip().upper()))
        if rate is None:
            return None
        return ExchangeRate(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            # Vigente el día que se pregunte: un fixture no caduca porque no
            # viene de ningún día concreto. Lo que sí hace es decir que es un
            # fixture, y eso viaja en cada conversión que produce.
            effective_date=on,
            source=SOURCE,
            provenance=SupplierFactProvenance.SIMULATED,
        )
