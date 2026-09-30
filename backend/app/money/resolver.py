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
from app.integrations.ports import ProviderKind
from app.money.ecb import EcbExchangeRateProvider
from app.money.manual import ManualExchangeRateProvider
from app.money.rates import ExchangeRate, ExchangeRateProvider


class CompositeExchangeRateProvider:
    """Varias fuentes en orden. La primera que dé una tasa **aceptable** manda.

    «Aceptable» es que la tasa no sea del futuro y esté dentro de su ventana de
    antigüedad (Milestone 42). Antes bastaba con que contestara, y una tasa manual
    de hace seis semanas tapaba una referencia de ayer: la conversión la rechazaba
    por vieja y el análisis quedaba no evaluable teniendo una tasa buena detrás.

    Si **ninguna** es aceptable se devuelve la primera que contestó, caducada, para
    que quien convierta la rechace con su motivo (`StaleRateError`) en vez de
    confundir «tasa vieja» con «no hay tasa».
    """

    name = "composite-exchange-rates"

    def __init__(self, sources: list[ExchangeRateProvider]) -> None:
        self._sources = sources

    def rate_for(self, *, base: str, quote: str, on: datetime.date) -> ExchangeRate | None:
        unacceptable: ExchangeRate | None = None
        for source in self._sources:
            rate = source.rate_for(base=base, quote=quote, on=on)
            if rate is None:
                continue
            if rate.is_acceptable_on(on):
                return rate
            if unacceptable is None:
                unacceptable = rate
        return unacceptable


def exchange_rates_for(db: Session, settings: Settings | None = None) -> ExchangeRateProvider:
    """La fuente activa.

    Lo que una persona haya declarado gana siempre que siga siendo aceptable: es un
    dato del mundo, y el fixture no. Y si el entorno no admite datos simulados, el fixture ni
    siquiera se monta.
    """
    config = settings or get_settings()
    sources: list[ExchangeRateProvider] = [ManualExchangeRateProvider(db)]
    if config.exchange_rate_provider is ProviderKind.REAL:
        # Lo declarado primero; después la referencia del BCE ya guardada; el
        # fixture solo detrás y solo donde se admiten datos simulados.
        sources.append(EcbExchangeRateProvider(db, max_age_days=config.ecb_rate_max_age_days))
    if config.allows_simulated_providers:
        sources.append(MockExchangeRateProvider())
    return CompositeExchangeRateProvider(sources)
