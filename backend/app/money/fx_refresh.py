"""Ingerir las referencias del BCE en `exchange_rates` (Milestone 42, ADR 0020).

Es el lado escritura del contrato FX: trae observaciones de la fuente y las guarda.
El análisis económico **no pasa por aquí**: lee lo ya guardado (`ecb.py`).

## La identidad de una observación

Una observación del BCE es `(par, fecha efectiva, fuente, tasa)`. De ahí salen las
dos reglas:

- **La misma observación otra vez no se duplica.** Se compara con la observación
  *más reciente* de ese par y esa fecha: si trae la misma tasa, no se escribe.
- **Una tasa distinta para el mismo par y fecha es una republicación.** El BCE puede
  republicar hasta el siguiente día TARGET. Se escribe una fila **nueva**, la
  anterior se conserva, la más reciente gana al leer, y queda auditada con los dos
  valores.

Se compara contra la más reciente y no contra «alguna anterior» a propósito: si el
BCE publica A, luego B y luego A otra vez, la tercera observación es legítima y
gana. Una restricción única sobre la tasa la habría rechazado.

## Todo o nada

La fuente se lee entera y se valida entera **antes** de tocar la base de datos. Si
falla la red, el XML está mal formado, viene vacío o trae algo inesperado, no se
guarda nada, no se borra nada y no se declara «sin cambios». Lo ya guardado sigue
valiendo mientras su ventana lo permita.

## El histórico de 90 días es recuperación explícita

`refresh_daily` no cae al histórico cuando el diario falla. `backfill_history` es
otra operación, con su propio permiso de llamarla, y solo la pide una persona.
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AmazonaError, ValidationError
from app.core.ids import new_correlation_id
from app.costs.service import CostMeter
from app.db.models.audit import AuditLog
from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.integrations.fx.ecb import (
    BASE_CURRENCY,
    EcbReferenceRateFeed,
    FeedUnavailableError,
)
from app.integrations.ports import ExchangeRateFeed, ProviderKind, ReferenceRateSet
from app.integrations.usage_rights import UsageRight, permits
from app.money.ecb import ECB_SOURCE, ISSUER, PROVIDER_NAME
from app.money.rates import ExchangeRate
from app.sourcing.provenance import SupplierFactProvenance
from app.sourcing.trade_terms import currency_for

MODE_DAILY = "daily"
MODE_BACKFILL = "backfill"
_NOTES = {
    MODE_DAILY: "ECB euro foreign exchange reference rates, daily file (eurofxref-daily.xml)",
    MODE_BACKFILL: "ECB euro foreign exchange reference rates, 90-day file (eurofxref-hist-90d.xml)",
}


def _plain(value: Decimal) -> Decimal:
    """`1.13550000` (lo que devuelve la columna `Numeric(18, 8)`) como `1.1355`, que es
    lo que el BCE publicó. No cambia el valor: quita ceros de relleno."""
    return Decimal(format(value.normalize(), "f"))


class FxSourceNotConfiguredError(AmazonaError):
    """No hay una fuente real de tipos de cambio configurada, o sus derechos no
    permiten guardar lo que devuelve. No se llama a nadie."""


@dataclass(frozen=True)
class Republication:
    pair: str
    effective_date: datetime.date
    previous_rate: Decimal
    new_rate: Decimal


@dataclass
class RefreshResult:
    """Lo que hizo un refresco, para que nadie tenga que adivinarlo."""

    mode: str
    #: Días de la fuente que se examinaron.
    days_examined: int
    #: Fecha efectiva más reciente que trajo la fuente. Es la de la fuente: no la
    #: de hoy ni la de la consulta.
    latest_effective_date: datetime.date
    ingested_at: datetime.datetime
    #: Observaciones nuevas (par y fecha que no teníamos).
    stored: int = 0
    #: Observaciones idénticas a la más reciente que ya teníamos: no se escriben.
    unchanged: int = 0
    #: Mismo par y fecha con **otra** tasa: se escribe una fila nueva y se audita.
    republished: list[Republication] = field(default_factory=list)
    #: Monedas que el BCE publica y que **no** están en nuestro catálogo. No se
    #: guardan ni se añaden al catálogo.
    omitted_currencies: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "days_examined": self.days_examined,
            "latest_effective_date": self.latest_effective_date.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "stored": self.stored,
            "unchanged": self.unchanged,
            "republished": [
                {
                    "pair": item.pair,
                    "effective_date": item.effective_date.isoformat(),
                    "previous_rate": str(item.previous_rate),
                    "new_rate": str(item.new_rate),
                }
                for item in self.republished
            ],
            "omitted_currencies": self.omitted_currencies,
        }


class FxRefreshService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        *,
        feed: ExchangeRateFeed | None = None,
    ) -> None:
        self._db = db
        self._settings = settings or get_settings()
        self._feed = feed

    # ------------------------------------------------------------ operaciones

    def refresh_daily(self, *, actor: str, correlation_id: str | None = None) -> RefreshResult:
        """El camino normal: el fichero diario, un día."""
        correlation_id = correlation_id or new_correlation_id()
        feed = self._resolve_feed(correlation_id)
        sets = self._call(lambda: [feed.fetch_daily()])
        return self._ingest(sets, mode=MODE_DAILY, actor=actor, correlation_id=correlation_id)

    def backfill_history(self, *, actor: str, correlation_id: str | None = None) -> RefreshResult:
        """Recuperación **explícita**: el histórico de 90 días. Nunca es el
        respaldo automático de un fallo del diario."""
        correlation_id = correlation_id or new_correlation_id()
        feed = self._resolve_feed(correlation_id)
        sets = self._call(feed.fetch_history)
        return self._ingest(sets, mode=MODE_BACKFILL, actor=actor, correlation_id=correlation_id)

    # ---------------------------------------------------------------- interno

    def _resolve_feed(self, correlation_id: str) -> ExchangeRateFeed:
        if self._settings.exchange_rate_provider is not ProviderKind.REAL:
            raise FxSourceNotConfiguredError(
                "no real exchange-rate source is configured (EXCHANGE_RATE_PROVIDER is not "
                "'real'): nothing is fetched, and nothing is assumed"
            )
        # «Tener el dato no es tener permiso» (ADR 0015): sin derecho a guardarlo
        # no se pregunta.
        if not permits(PROVIDER_NAME, UsageRight.STORAGE):
            raise FxSourceNotConfiguredError(
                f"the usage rights of {PROVIDER_NAME} do not allow storing what it returns"
            )
        if self._feed is not None:
            return self._feed
        meter = CostMeter(
            self._db, correlation_id=correlation_id, limits=self._settings.spend_limits
        )
        return EcbReferenceRateFeed(meter=meter)

    def _call(self, fetch: Callable[[], list[ReferenceRateSet]]) -> list[ReferenceRateSet]:
        """Llama a la fuente. Si falla no se guarda nada; solo se conserva la fila
        del contador de coste, que es el registro de que se intentó."""
        try:
            return fetch()
        except (AmazonaError, ValidationError):
            self._db.commit()
            raise

    def _ingest(
        self, sets: list[ReferenceRateSet], *, mode: str, actor: str, correlation_id: str
    ) -> RefreshResult:
        today = datetime.datetime.now(datetime.UTC).date()
        ingested_at = datetime.datetime.now(datetime.UTC)

        # 1. Validar y construir TODO antes de escribir nada.
        candidates: list[ExchangeRate] = []
        omitted: set[str] = set()
        for item in sorted(sets, key=lambda entry: entry.published_on):
            if item.base != BASE_CURRENCY:
                raise FeedUnavailableError(
                    f"the feed quotes against {item.base}, not {BASE_CURRENCY}: not stored"
                )
            if item.published_on > today:
                raise FeedUnavailableError(
                    f"the feed carries a rate dated {item.published_on}, in the future"
                )
            for code, value in sorted(item.rates.items()):
                try:
                    currency_for(code)
                except ValidationError:
                    # Fuera del catálogo: se lista y no se guarda. Ampliar el
                    # catálogo es una decisión aparte.
                    omitted.add(code)
                    continue
                candidates.append(
                    ExchangeRate(
                        base_currency=BASE_CURRENCY,
                        quote_currency=code,
                        rate=value,
                        effective_date=item.published_on,
                        source=ECB_SOURCE,
                        provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED,
                        declared_by=ISSUER,
                    )
                )
        if not candidates:
            raise FeedUnavailableError(
                "the feed carries no currency that this system admits: nothing to store, "
                "and 'no change' is not assumed"
            )

        result = RefreshResult(
            mode=mode,
            days_examined=len(sets),
            latest_effective_date=max(item.published_on for item in sets),
            ingested_at=ingested_at,
            omitted_currencies=sorted(omitted),
        )

        # 2. Escribir, todo en una transacción.
        try:
            for candidate in candidates:
                latest = (
                    self._db.query(ExchangeRateRow)
                    .filter(
                        ExchangeRateRow.base_currency == candidate.base_currency,
                        ExchangeRateRow.quote_currency == candidate.quote_currency,
                        ExchangeRateRow.effective_date == candidate.effective_date,
                        ExchangeRateRow.source == candidate.source,
                    )
                    .order_by(ExchangeRateRow.created_at.desc())
                    .first()
                )
                if latest is not None and Decimal(str(latest.rate)) == candidate.rate:
                    result.unchanged += 1
                    continue
                self._db.add(
                    ExchangeRateRow(
                        base_currency=candidate.base_currency,
                        quote_currency=candidate.quote_currency,
                        rate=candidate.rate,
                        effective_date=candidate.effective_date,
                        source=candidate.source,
                        provenance=candidate.provenance.value,
                        declared_by=candidate.declared_by,
                        note=_NOTES[mode],
                        created_at=datetime.datetime.now(datetime.UTC),
                    )
                )
                if latest is None:
                    result.stored += 1
                    continue
                republication = Republication(
                    pair=candidate.pair,
                    effective_date=candidate.effective_date,
                    previous_rate=_plain(Decimal(str(latest.rate))),
                    new_rate=candidate.rate,
                )
                result.republished.append(republication)
                self._db.add(
                    AuditLog(
                        actor=actor,
                        action="exchange_rate.ecb_republished",
                        resource=f"exchange_rate:{candidate.pair}",
                        before={
                            "rate": str(republication.previous_rate),
                            "effective_date": candidate.effective_date.isoformat(),
                        },
                        after={
                            "rate": str(republication.new_rate),
                            "effective_date": candidate.effective_date.isoformat(),
                        },
                        correlation_id=correlation_id,
                    )
                )
            self._db.add(
                AuditLog(
                    actor=actor,
                    action=f"exchange_rate.ecb_{mode}",
                    resource="exchange_rate:ecb",
                    before=None,
                    after=result.summary(),
                    correlation_id=correlation_id,
                )
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return result
