"""La frontera entre el dinero exacto y el resto del repositorio (Milestone 40).

El dominio monetario usa `Decimal`. El resto del sistema —treinta migraciones de
columnas `Float`, varias columnas `JSON`, y un navegador que no tiene decimales
exactos— usa `float`. Migrar todo eso es un milestone propio y **no es este**.

Lo que sí es este milestone: que el cruce tenga **una puerta por sentido, con su
regla escrita**, en vez de ocurrir por accidente en veinte sitios.

## Las tres puertas

**Columna `Float` legada → dominio.** `Money.from_legacy_float`, que convierte
por la representación decimal y no por la binaria: `Decimal(0.1)` no es 0,1.

**Dominio → columna `JSON`.** Cadena, nunca `float`. `json.dumps` no sabe
serializar un `Decimal`, y convertirlo a `float` para que pase tiraría lo que se
acaba de ganar.

**Dominio → navegador.** Cadena más moneda. En JavaScript un número es un
`float64`; mandar `6.4` devolvería el error por la puerta de atrás.

Un importe viaja como `{"amount": "6.4000", "currency": "EUR"}`. Es más feo que
un número y es exacto, y el cálculo del navegador está declarado como simulación
de interfaz, nunca como resultado oficial.
"""

from decimal import Decimal
from typing import Any

from app.core.errors import ValidationError
from app.money.money import Money
from app.money.rates import Conversion


def money_to_json(amount: Money | None) -> dict[str, str] | None:
    """Un importe listo para una columna `JSON` o para la API.

    `None` se conserva como `None`: un importe ausente no se convierte en cero
    al serializarse, que sería la forma más tonta de perder toda la disciplina
    del Milestone 39.
    """
    if amount is None:
        return None
    return {"amount": str(amount.amount), "currency": amount.currency}


def money_from_json(payload: dict[str, Any] | None) -> Money | None:
    """El camino de vuelta. Exige cadena: si lo guardado es un número, alguien
    se saltó la puerta y conviene que se vea."""
    if payload is None:
        return None
    raw = payload.get("amount")
    if isinstance(raw, float):
        raise ValidationError(
            "a stored amount came back as a float: it was serialized without going "
            "through money_to_json, and its exactness is already gone"
        )
    return Money(amount=Decimal(str(raw)), currency=str(payload["currency"]))


def conversion_to_json(conversion: Conversion | None) -> dict[str, Any] | None:
    """Los diez campos de una conversión, tal cual, para guardarlos con el
    análisis. Se guardan todos: el que falte es el que hará falta."""
    if conversion is None:
        return None
    return {
        "source_currency": conversion.source_currency,
        "source_amount": str(conversion.source_amount),
        "target_currency": conversion.target_currency,
        "converted_amount": str(conversion.converted_amount),
        "rate": str(conversion.rate),
        "pair": conversion.pair,
        "direction": conversion.direction.value,
        "effective_date": conversion.effective_date.isoformat(),
        "source": conversion.source,
        "provenance": conversion.provenance.value,
    }


def decimal_to_json(value: Decimal | None) -> str | None:
    """Un número exacto sin moneda —una tasa, una fracción de margen— para una
    columna `JSON`."""
    return None if value is None else str(value)


def legacy_float(amount: Money | None) -> float | None:
    """Salida hacia una columna `Float` que ya existía.

    Se redondea a dos decimales antes de salir, para que lo que la columna
    guarde sea el importe presentable y no una cola binaria: si el destino no
    puede ser exacto, al menos que sea deliberado.
    """
    return None if amount is None else float(amount.rounded().amount)
