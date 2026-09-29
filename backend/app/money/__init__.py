"""Dinero con moneda, y aritmética que se niega a mezclarlas (Milestone 40).

Tres módulos:

- `money.py`: un importe **no existe sin su moneda**, y sumar dos monedas
  distintas falla al construir el resultado, no al mostrarlo.
- `rates.py`: una conversión es un hecho con procedencia, fecha y par sin
  ambigüedad. Sin tasa no hay conversión: hay `NOT_EVALUABLE`.
- `serialization.py`: la frontera entre este dominio, que usa `Decimal`, y el
  resto del repositorio, que usa `float` y columnas JSON.
"""

from app.money.money import (
    DISPLAY_PLACES,
    INTERNAL_PLACES,
    CurrencyMismatchError,
    Money,
)
from app.money.rates import (
    MAX_RATE_AGE_DAYS,
    Conversion,
    ExchangeRate,
    NoRateAvailableError,
    RateDirection,
    StaleRateError,
)

__all__ = [
    "DISPLAY_PLACES",
    "INTERNAL_PLACES",
    "MAX_RATE_AGE_DAYS",
    "Conversion",
    "CurrencyMismatchError",
    "ExchangeRate",
    "Money",
    "NoRateAvailableError",
    "RateDirection",
    "StaleRateError",
]
