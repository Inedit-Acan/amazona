"""Qué fuente de tipos de cambio se usa, y dónde (Milestone 40, ADR 0018).

Lo declarado primero, el fixture después — y el fixture **solo donde la ADR 0008
admite datos simulados**. Es la misma composición que Product Intelligence:
`CompositeProductSignalProvider` pone lo real delante y el relleno detrás, y un
entorno que no admite fixtures no monta el relleno.

La consecuencia importante está en el otro extremo: en producción, una
cotización en dólares sin tasa declarada deja el análisis **no evaluable**. Es
incómodo y es lo correcto: el margen de un producto no puede depender de un
número que nadie ha puesto.
"""

import datetime

from sqlalchemy.orm import Session

from app.ai.mock_exchange_rates import MockExchangeRateProvider
from app.core.config import Settings, get_settings
from app.money.manual import ManualExchangeRateProvider
from app.money.rates import ExchangeRate, ExchangeRateProvider


class CompositeExchangeRateProvider:
    """Varias fuentes en orden. La primera que conteste manda."""

    name = "composite-exchange-rates"

    def __init__(self, sources: list[ExchangeRateProvider]) -> None:
        self._sources = sources

    def rate_for(self, *, base: str, quote: str, on: datetime.date) -> ExchangeRate | None:
        for source in self._sources:
            rate = source.rate_for(base=base, quote=quote, on=on)
            if rate is not None:
                return rate
        return None


def exchange_rates_for(db: Session, settings: Settings | None = None) -> ExchangeRateProvider:
    """La fuente activa.

    Lo que una persona haya declarado gana siempre: es un dato del mundo, y el
    fixture no. Y si el entorno no admite datos simulados, el fixture ni
    siquiera se monta.
    """
    config = settings or get_settings()
    sources: list[ExchangeRateProvider] = [ManualExchangeRateProvider(db)]
    if config.allows_simulated_providers:
        sources.append(MockExchangeRateProvider())
    return CompositeExchangeRateProvider(sources)
