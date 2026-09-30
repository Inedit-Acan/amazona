"""Apoyo compartido de las pruebas del refresco del BCE (Milestone 42).

Módulo auxiliar de tests, **no** un test: aquí viven la fuente falsa y los
constructores de conjuntos de tasas, para que los ficheros de test los importen
de un sitio común. Se importa por su nombre (`from ecb_test_support import ...`),
igual que `regulatory_test_support.py`.
"""

import datetime
from decimal import Decimal

from app.core.config import Settings
from app.integrations.fx.ecb import FeedUnavailableError
from app.integrations.ports import ProviderKind, ReferenceRateSet
from app.money.ecb import PROVIDER_NAME

RETRIEVED = datetime.datetime(2026, 9, 29, 14, 5, tzinfo=datetime.UTC)
URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

#: Lo que el BCE publicó el 29-09-2026 para las monedas que el catálogo admite,
#: más cuatro que **no** admite (JPY, CHF, CZK, VND no está: no lo publica).
REAL_RATES = {
    "USD": Decimal("1.1355"),
    "GBP": Decimal("0.85718"),
    "CNY": Decimal("7.6117"),
    "HKD": Decimal("8.9091"),
    "MXN": Decimal("20.3222"),
    "PLN": Decimal("4.3653"),
    "JPY": Decimal("178.41"),
    "CHF": Decimal("0.9461"),
    "CZK": Decimal("24.411"),
}
ADMITTED = {"USD", "GBP", "CNY", "HKD", "MXN", "PLN"}
OMITTED = ["CHF", "CZK", "JPY"]


def rate_set(published_on: datetime.date, rates: dict[str, Decimal] | None = None) -> ReferenceRateSet:
    return ReferenceRateSet(
        provider=PROVIDER_NAME,
        published_on=published_on,
        base="EUR",
        rates=dict(REAL_RATES if rates is None else rates),
        retrieved_at=RETRIEVED,
        source_url=URL,
    )


class FakeFeed:
    """Una fuente que responde lo que se le diga y anota cada petición."""

    name = PROVIDER_NAME

    def __init__(
        self,
        daily: ReferenceRateSet | Exception | None = None,
        history: list[ReferenceRateSet] | Exception | None = None,
    ) -> None:
        self.daily = daily
        self.history = history
        self.daily_calls = 0
        self.history_calls = 0

    def fetch_daily(self) -> ReferenceRateSet:
        self.daily_calls += 1
        if isinstance(self.daily, Exception):
            raise self.daily
        if self.daily is None:
            raise FeedUnavailableError("nothing scripted")
        return self.daily

    def fetch_history(self) -> list[ReferenceRateSet]:
        self.history_calls += 1
        if isinstance(self.history, Exception):
            raise self.history
        if self.history is None:
            raise FeedUnavailableError("nothing scripted")
        return self.history


def real_settings(**overrides) -> Settings:
    """Ajustes con la fuente real activada, sin leer `backend/.env` (que apunta a
    Supabase)."""
    return Settings(_env_file=None, exchange_rate_provider=ProviderKind.REAL, **overrides)
