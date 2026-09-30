"""Tipos de cambio de referencia del BCE, lado lectura (Milestone 42, ADR 0020).

El BCE publica cada día laborable TARGET, sobre las 16:00 CET, cuántas unidades de
cada divisa valen **un euro**. Esa publicación se ingiere aparte (`fx_refresh.py`)
y se guarda en `exchange_rates`. Este proveedor **solo lee la base de datos**: el
análisis económico nunca hace una petición HTTP.

## Lo que esta tasa es, y lo que no

- Es una **referencia informativa**. El propio BCE dice que no debe usarse para
  transacciones. Aquí sirve para estimar un margen; no es la tasa que aplica un
  banco o un procesador de pagos, cuyo diferencial no está incluido.
- «Procedencia `third_party_verified`» quiere decir que un emisor con nombre
  —el BCE— sostiene la cifra, no que sea la cotización que se va a pagar.
- Solo hay pares EUR/divisa. No hay cruces (USD/GBP se **calcularía**, y eso es
  otro milestone: ADR 0020 §7).

## La fecha efectiva no se toca

Sábado, domingo y festivos TARGET no hay publicación. El lunes se usa la tasa del
viernes **con fecha de viernes**, y tiene tres días. Es la fecha de la fuente; no
se traslada al día que la usamos.
"""

import datetime

from sqlalchemy.orm import Session

from app.integrations.usage_rights import UsageRight, permits
from app.money.manual import ECB_SOURCE_PREFIX, best_stored_rate
from app.money.rates import ExchangeRate

#: El mismo nombre en la matriz de derechos, en la política de coste y en el
#: contador.
PROVIDER_NAME = "ecb-reference-rates"
#: Toda tasa ingerida del BCE lleva esta fuente, venga del fichero diario o del
#: histórico: es lo que hace que la misma observación sea la misma observación.
ECB_SOURCE = f"{ECB_SOURCE_PREFIX}eurofxref"
ISSUER = "European Central Bank"
#: Ventana por defecto. Cubre el hueco máximo observado entre publicaciones (tres
#: días de fin de semana; algo más con un festivo TARGET) y deja unos días de
#: margen si el refresco falla. Configurable: `ECB_RATE_MAX_AGE_DAYS`.
DEFAULT_MAX_AGE_DAYS = 7

ATTRIBUTION = "Fuente: Banco Central Europeo (BCE), tipos de cambio de referencia del euro."
NOTICE = (
    "Referencia informativa del BCE: no es la tasa transaccional que aplica un banco o un "
    "procesador de pagos."
)

#: Lo que hace falta poder hacer con un dato para usarlo en un margen: leerlo de
#: lo guardado, transformarlo (invertirlo) y derivar una cifra propia de él.
_REQUIRED_RIGHTS = (UsageRight.STORAGE, UsageRight.TRANSFORMATION, UsageRight.DERIVED_METRICS)


def is_ecb_source(source: str) -> bool:
    return source.startswith(ECB_SOURCE_PREFIX)


class EcbExchangeRateProvider:
    """Las referencias del BCE ya guardadas, leídas de la base de datos."""

    name = "ecb-exchange-rates"

    def __init__(self, db: Session, *, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
        self._db = db
        self._max_age_days = max_age_days

    def rate_for(self, *, base: str, quote: str, on: datetime.date) -> ExchangeRate | None:
        """La referencia aplicable, o `None`.

        Sin derechos escritos no se lee: «tener el dato no es tener permiso». Busca
        el par en los dos sentidos; el BCE publica `EUR/USD`, así que `USD→EUR` es
        la misma tasa invertida, y la conversión lo registra.
        """
        if not all(permits(PROVIDER_NAME, right) for right in _REQUIRED_RIGHTS):
            return None
        direct = self._best(base=base, quote=quote, on=on)
        if direct is not None:
            return direct
        return self._best(base=quote, quote=base, on=on)

    def _best(self, *, base: str, quote: str, on: datetime.date) -> ExchangeRate | None:
        return best_stored_rate(
            self._db,
            base=base,
            quote=quote,
            on=on,
            from_ecb=True,
            max_age_days=self._max_age_days,
        )
