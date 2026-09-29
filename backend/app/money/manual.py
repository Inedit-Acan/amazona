"""Tipos de cambio que escribe una persona (Milestone 40, ADR 0018).

El único proveedor de tasas de este milestone. Lee la tabla `exchange_rates` y
**no toca la red**: presupuesto cero, sin altas, sin credenciales.

No es un mock. Un cambio que el banco aplicó de verdad a una transferencia de
verdad es un dato real; lo que no tiene es automatismo. Es exactamente el mismo
razonamiento que sostuvo la entrada manual de proveedores del Milestone 39: la
fuente real más barata que existe somos nosotros.

## Cómo elige

Para un par y una fecha, la tasa **más reciente que no sea posterior a esa
fecha**. Nunca una del futuro —convertir marzo con el cambio de abril es mirar
la respuesta antes de hacer el examen— y nunca una de otro par «parecida».

Si hay varias del mismo día, gana la de procedencia más fuerte y, entre iguales,
la escrita más tarde: una corrección posterior corrige.
"""

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.money.rates import ExchangeRate
from app.sourcing.provenance import SupplierFactProvenance, rank


class ManualExchangeRateProvider:
    """Tasas declaradas a mano, leídas de la base de datos."""

    name = "manual-exchange-rates"

    def __init__(self, db: Session) -> None:
        self._db = db

    def rate_for(
        self, *, base: str, quote: str, on: datetime.date
    ) -> ExchangeRate | None:
        """La tasa aplicable, o `None`.

        Busca el par en los dos sentidos: quien declaró `USD/EUR` no tiene que
        declarar además `EUR/USD`. Cuál se usó lo registra la conversión, porque
        invertir una tasa no es gratis.
        """
        direct = self._best(base=base, quote=quote, on=on)
        if direct is not None:
            return direct
        return self._best(base=quote, quote=base, on=on)

    def _best(self, *, base: str, quote: str, on: datetime.date) -> ExchangeRate | None:
        rows = (
            self._db.query(ExchangeRateRow)
            .filter(
                ExchangeRateRow.base_currency == base.strip().upper(),
                ExchangeRateRow.quote_currency == quote.strip().upper(),
                ExchangeRateRow.effective_date <= on,
            )
            .all()
        )
        if not rows:
            return None

        def preference(row: ExchangeRateRow) -> tuple[datetime.date, int, datetime.datetime]:
            return (
                row.effective_date,
                -rank(SupplierFactProvenance(row.provenance)),
                row.created_at,
            )

        chosen = max(rows, key=preference)
        return ExchangeRate(
            base_currency=chosen.base_currency,
            quote_currency=chosen.quote_currency,
            rate=Decimal(str(chosen.rate)),
            effective_date=chosen.effective_date,
            source=chosen.source,
            provenance=SupplierFactProvenance(chosen.provenance),
            declared_by=chosen.declared_by,
        )
