"""Una conversión es un hecho con procedencia (Milestone 40, ADR 0018).

La ADR 0017 prohibió convertir entre monedas, y tenía razón con lo que había:
convertir exige un tipo de cambio, y un tipo de cambio inventado mete un error
del 5 % en el margen sin que nadie lo vea. Lo que la 0017 no podía hacer era
dejar el sistema sin margen calculable para siempre.

Esta ADR no levanta la prohibición: la **completa**. Lo prohibido sigue siendo
convertir sin fuente. Lo que se añade es una fuente —de momento, un tipo de
cambio que declara una persona— y un registro que conserva todo lo necesario
para responder, dentro de seis meses, «¿con qué cambio se decidió esto?».

## Lo que una conversión conserva

Moneda origen, importe origen, moneda destino, importe convertido, tasa, **par
sin ambigüedad**, dirección, fecha efectiva, fuente y procedencia. Diez campos
para multiplicar dos números, y ninguno sobra: sin el par y la dirección,
«1,08» puede ser dólares por euro o euros por dólar, y la diferencia es del 16 %.

## Lo que NO hay

- **No hay 1:1.** Sin tasa aplicable no hay conversión: hay `NOT_EVALUABLE`.
- **No hay red.** El único proveedor de este milestone lee tasas que alguien ha
  escrito a mano. Una fuente oficial —el BCE publica referencias diarias
  gratis— se estudia aparte y no es dependencia de nada.
- **No hay tasa vieja sirviendo de comodín.** Pasada la ventana, una tasa deja
  de valer. Una de hace seis meses es peor que no tener ninguna, porque tiene
  aspecto de dato.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.core.errors import ValidationError
from app.money.money import Money
from app.sourcing.provenance import STORABLE, SupplierFactProvenance
from app.sourcing.trade_terms import currency_for

#: Cuánto puede envejecer una tasa antes de dejar de valer. Treinta días es la
#: ventana de una negociación con proveedor, que es el uso real que tiene esto
#: hoy: el cambio que aplicó el banco en la transferencia del mes.
#:
#: Es un número escrito a mano y discutible. Lo que no es discutible es que
#: exista: sin techo, la tasa de hace dos años seguiría convirtiendo.
MAX_RATE_AGE_DAYS = 30


class RateDirection(StrEnum):
    """Cómo se usó la tasa.

    `INVERTED` no es un detalle de implementación: una tasa USD→EUR usada al
    revés para convertir euros a dólares es **la misma tasa aplicada de otra
    manera**, y quien audite el número tiene que poder verlo. Los diferenciales
    de compra y venta no son simétricos, así que invertir no es gratis.
    """

    DIRECT = "direct"
    INVERTED = "inverted"


class NoRateAvailableError(ValidationError):
    """No hay tasa para este par y esta fecha.

    Es un error y no un `None` silencioso porque quien llama tiene que decidir
    qué hacer, y lo único correcto es declarar el cálculo no evaluable.
    """


class StaleRateError(NoRateAvailableError):
    """Hay tasa y es demasiado vieja para usarla."""


@dataclass(frozen=True)
class ExchangeRate:
    """Una tasa declarada: `1 base = rate quote`.

    La dirección vive en los nombres de los campos, no en un comentario. Es la
    única forma de que una fila cruda se entienda sin documentación al lado.
    """

    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_date: datetime.date
    #: De dónde salió: `manual:<usuario>`, o el emisor cuando lo haya.
    source: str
    #: Quién la sostiene. Hoy `declared` (la escribe el operador) o
    #: `third_party_verified` si viene de un emisor con nombre.
    provenance: SupplierFactProvenance = SupplierFactProvenance.DECLARED
    #: Obligatorio cuando la procedencia es `third_party_verified`.
    declared_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rate, Decimal):
            raise ValidationError("an exchange rate must be a Decimal, not a float")
        if self.rate <= 0:
            raise ValidationError(f"an exchange rate must be positive, got {self.rate}")
        currency_for(self.base_currency)
        currency_for(self.quote_currency)
        object.__setattr__(self, "base_currency", self.base_currency.strip().upper())
        object.__setattr__(self, "quote_currency", self.quote_currency.strip().upper())
        if self.base_currency == self.quote_currency:
            raise ValidationError(
                "an exchange rate between a currency and itself is not a rate: "
                "converting EUR to EUR needs no conversion at all"
            )
        if self.provenance not in STORABLE:
            raise ValidationError(
                f"an exchange rate cannot be declared {self.provenance}: "
                "a rate nobody stands behind is the 1:1 assumption with extra steps"
            )
        if self.provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (
            self.declared_by or ""
        ).strip():
            raise ValidationError(
                "a third-party verified rate must name the issuer (ADR 0017)"
            )

    @property
    def pair(self) -> str:
        """El par, sin ambigüedad: `USD/EUR` significa cuántos EUR vale 1 USD."""
        return f"{self.base_currency}/{self.quote_currency}"

    def age_in_days(self, on: datetime.date) -> int:
        return (on - self.effective_date).days


@dataclass(frozen=True)
class Conversion:
    """Lo que quedó registrado de haber convertido un importe.

    Se guarda entero con el análisis. No es trazabilidad decorativa: el margen
    de un producto depende de este número, y una decisión de compra que no se
    puede reconstruir es una decisión que no se puede revisar.
    """

    source_currency: str
    source_amount: Decimal
    target_currency: str
    converted_amount: Decimal
    rate: Decimal
    #: El par tal y como se declaró la tasa, no el de la conversión.
    pair: str
    direction: RateDirection
    effective_date: datetime.date
    source: str
    provenance: SupplierFactProvenance

    @property
    def converted(self) -> Money:
        return Money(amount=self.converted_amount, currency=self.target_currency)


def convert(
    amount: Money, *, to: str, rate: ExchangeRate, on: datetime.date | None = None
) -> Conversion:
    """Convierte un importe con una tasa concreta, y deja constancia.

    Acepta la tasa en cualquiera de los dos sentidos y **dice cuál usó**. Lo que
    no hace nunca es buscarse una tasa por su cuenta: quien llama decide con qué
    convierte, porque esa decisión es parte del resultado.
    """
    target = to.strip().upper()
    currency_for(target)
    today = on or datetime.datetime.now(datetime.UTC).date()

    if amount.currency == target:
        raise ValidationError(
            f"converting {target} to itself is not a conversion; "
            "check the caller before recording a rate that was never applied"
        )

    age = rate.age_in_days(today)
    if age > MAX_RATE_AGE_DAYS:
        raise StaleRateError(
            f"the {rate.pair} rate of {rate.effective_date} is {age} days old, past the "
            f"{MAX_RATE_AGE_DAYS}-day window: a rate this old looks like data and is not"
        )
    if age < 0:
        raise ValidationError(
            f"the {rate.pair} rate is dated {rate.effective_date}, in the future"
        )

    if rate.base_currency == amount.currency and rate.quote_currency == target:
        direction = RateDirection.DIRECT
        applied = rate.rate
    elif rate.base_currency == target and rate.quote_currency == amount.currency:
        # La misma tasa al revés. Se registra, porque no es gratis: los
        # diferenciales de compra y de venta no son simétricos.
        direction = RateDirection.INVERTED
        applied = Decimal(1) / rate.rate
    else:
        raise NoRateAvailableError(
            f"the {rate.pair} rate does not apply to {amount.currency}->{target}"
        )

    converted = Money(amount=amount.amount * applied, currency=target)
    return Conversion(
        source_currency=amount.currency,
        source_amount=amount.amount,
        target_currency=target,
        converted_amount=converted.amount,
        rate=rate.rate,
        pair=rate.pair,
        direction=direction,
        effective_date=rate.effective_date,
        source=rate.source,
        provenance=rate.provenance,
    )


class ExchangeRateProvider(Protocol):
    """De dónde salen las tasas.

    Un protocolo y no una clase para que el día que haya una fuente oficial
    —el BCE u otra— entre por aquí sin que nada de economía cambie, igual que
    los proveedores de señales del Milestone 34.
    """

    name: str

    def rate_for(
        self, *, base: str, quote: str, on: datetime.date
    ) -> ExchangeRate | None: ...
