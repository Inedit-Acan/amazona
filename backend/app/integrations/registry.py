"""Which provider is active for each external domain, and whether it is allowed
to be (Milestone 30, ADR 0008).

Two jobs:

1. Resolve the provider an agent should use, from explicit configuration rather
   than from a hardcoded default buried in the agent's constructor.
2. Refuse to run an enforcing environment on fixture data. `production` starting
   with MockTrendsProvider would mean real decisions taken on invented numbers,
   which is the single thing the plan maestro says must never happen.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from app.ai.mock_ad_performance_directory import MockAdPerformanceDirectory
from app.ai.mock_marketplace_directory import MockMarketplaceDirectory
from app.ai.mock_regulatory_directory import MockRegulatoryDirectory
from app.ai.mock_supplier_directory import MockSupplierDirectory
from app.core.config import Settings, get_settings
from app.costs.service import CallMeter, UnmeteredCalls
from app.integrations.ports import (
    IntegrationDomain,
    ProductSignalProvider,
    ProviderKind,
    RegulatoryAnchorSource,
)
from app.integrations.product_intelligence import (
    CompositeProductSignalProvider,
    MockProductSignalProvider,
    WikimediaPageviewsProvider,
)
from app.integrations.product_intelligence.ebay import (
    PRODUCTION_HOST,
    SANDBOX_HOST,
    EbayBrowseProvider,
)
from app.integrations.product_intelligence.langlinks import LanglinkResolver
from app.integrations.regulatory.eur_lex import EurLexCellarSource
from app.orders.simulated_fulfilment import SimulatedFulfilmentAdapter
from app.payments.providers.simulated import SimulatedPaymentProvider


class ProviderNotAvailableError(RuntimeError):
    """The configured provider does not exist yet. Raised instead of silently
    falling back to the mock: a deployment that asked for real data and got
    fixtures without noticing is the failure this whole milestone is about."""


@dataclass(frozen=True)
class ProviderBinding:
    """What is actually wired for a domain right now."""

    domain: IntegrationDomain
    kind: ProviderKind
    name: str
    #: Las fuentes reales configuradas, en orden, cuando el dominio usa más de
    #: una (Milestone 37). Vacío cuando no aplica: con una sola fuente el `name`
    #: ya lo dice todo, y una lista de un elemento no añade nada.
    sources: tuple[str, ...] = ()

    @property
    def is_simulated(self) -> bool:
        """Si esto puede servir datos inventados.

        `COMPOSITE` cuenta como simulado a propósito: aunque la mayoría de sus
        señales sean reales, puede rellenar con fixtures, y un panel que dijera
        «real» estaría mintiendo la parte que importa (Milestone 34).
        """
        return self.kind in (ProviderKind.MOCK, ProviderKind.COMPOSITE)


#: Every implementation the system knows about, per domain and kind. Real and
#: sandbox adapters are added here as they are built (Milestone 34 onwards); an
#: absent one is an error, never a silent downgrade to MOCK.
def _wikimedia_provider(settings: Settings, meter: CallMeter) -> WikimediaPageviewsProvider:
    return WikimediaPageviewsProvider(
        months=settings.wikimedia.months,
        max_requests=settings.wikimedia.max_requests,
        timeout=settings.wikimedia.timeout_seconds,
        meter=meter,
        # Sin resolutor, esta fuente solo sabe medir su proyecto por defecto: un
        # mercado en otro idioma se quedaría sin señal (Milestone 38).
        langlinks=LanglinkResolver(timeout=settings.wikimedia.timeout_seconds, meter=meter)
        if settings.wikimedia.resolve_languages
        else None,
    )


def _ebay_provider(settings: Settings, meter: CallMeter) -> EbayBrowseProvider:
    return EbayBrowseProvider(
        client_id=settings.ebay.client_id,
        client_secret=settings.ebay.client_secret,
        host=PRODUCTION_HOST if settings.ebay.use_production else SANDBOX_HOST,
        max_requests=settings.ebay.max_requests,
        timeout=settings.ebay.timeout_seconds,
        meter=meter,
    )


#: Los adaptadores reales de Product Intelligence, por su nombre estable — el
#: mismo que cada señal persiste en `provider` (Milestone 37, ADR 0015).
#:
#: Que esto sea un diccionario y no una cadena de `if` es lo que hace reversible
#: la elección de proveedor: añadir uno es añadir una entrada, y quitarlo es
#: quitarla. Nada más arriba sabe cuántos hay ni cómo se llaman.
REAL_PRODUCT_INTELLIGENCE_SOURCES: dict[str, Callable[[Settings, CallMeter], object]] = {
    WikimediaPageviewsProvider.name: _wikimedia_provider,
    EbayBrowseProvider.name: _ebay_provider,
}


class UnknownRealSourceError(RuntimeError):
    """Se ha configurado una fuente real que no existe. Se avisa al arrancar, no
    en la primera investigación: el mismo criterio que `ProviderNotAvailableError`
    (ADR 0008 §3)."""


def _real_sources(settings: Settings, meter: CallMeter) -> list[ProductSignalProvider]:
    """Las fuentes reales configuradas, en el orden configurado."""
    built: list[ProductSignalProvider] = []
    for name in settings.product_intelligence_real_sources:
        builder = REAL_PRODUCT_INTELLIGENCE_SOURCES.get(name)
        if builder is None:
            available = ", ".join(sorted(REAL_PRODUCT_INTELLIGENCE_SOURCES))
            raise UnknownRealSourceError(
                f"no real product intelligence adapter called {name!r}; available: {available}"
            )
        built.append(cast(ProductSignalProvider, builder(settings, meter)))
    if not built:
        raise UnknownRealSourceError(
            "product_intelligence_real_sources is empty: a real provider with no sources "
            "would answer nothing and look like a measurement of nothing"
        )
    return built


def _real_product_intelligence(settings: Settings, meter: CallMeter) -> ProductSignalProvider:
    """Lo que significa `real` cuando hay más de una fuente real (ADR 0015 §1).

    Una sola fuente se usa directamente. Varias se componen **entre reales**: la
    primera que da una señal manda y las siguientes rellenan lo que falte, igual
    que en `composite` — pero aquí no hay fixtures de por medio, así que el
    resultado **no es simulado** y sirve donde los datos simulados están
    prohibidos (ADR 0008 §4).
    """
    sources = _real_sources(settings, meter)
    if len(sources) == 1:
        return sources[0]
    return CompositeProductSignalProvider(sources)


def _real_regulatory(settings: Settings, meter: CallMeter) -> RegulatoryAnchorSource:
    return EurLexCellarSource(meter=meter)


def _composite_product_intelligence(settings: Settings, meter: CallMeter) -> ProductSignalProvider:
    """Lo real primero, el relleno después (ADR 0008 y ADR 0012)."""
    return CompositeProductSignalProvider(
        [*_real_sources(settings, meter), MockProductSignalProvider()]
    )


#: Adaptadores que necesitan configuración para construirse. Se mantienen aparte
#: de `IMPLEMENTATIONS` —que sigue siendo quien dice si un proveedor existe y
#: cómo se llama— para que el nombre que aparece en el panel siga siendo el de
#: la clase y no el de una función de fábrica.
BUILDERS: dict[
    tuple[IntegrationDomain, ProviderKind], Callable[[Settings, CallMeter], object]
] = {
    (IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.REAL): _real_product_intelligence,
    (IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.SANDBOX): _real_product_intelligence,
    (IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.COMPOSITE): _composite_product_intelligence,
    (IntegrationDomain.REGULATORY, ProviderKind.REAL): _real_regulatory,
}


#: Qué implementación existe para cada dominio y tipo, y cómo se llama. Las que
#: necesitan configuración se construyen en `BUILDERS`; aquí figuran por su
#: clase, que es el nombre que el panel enseña.
IMPLEMENTATIONS: dict[IntegrationDomain, dict[ProviderKind, Callable[..., object]]] = {
    IntegrationDomain.PRODUCT_INTELLIGENCE: {
        ProviderKind.MOCK: MockProductSignalProvider,
        ProviderKind.REAL: WikimediaPageviewsProvider,
        # El entorno de pruebas de eBay es lo que da contenido a `SANDBOX`, que
        # desde la ADR 0008 era una casilla del enum sin nada detrás.
        ProviderKind.SANDBOX: EbayBrowseProvider,
        ProviderKind.COMPOSITE: CompositeProductSignalProvider,
    },
    IntegrationDomain.SUPPLIERS: {ProviderKind.MOCK: MockSupplierDirectory},
    IntegrationDomain.REGULATORY: {
        ProviderKind.MOCK: MockRegulatoryDirectory,
        # Ancla normas que una persona declara (ADR 0019). No responde «qué se
        # exige a esta categoría»: ese juicio no lo da ninguna fuente pública.
        ProviderKind.REAL: EurLexCellarSource,
    },
    IntegrationDomain.ADS: {ProviderKind.MOCK: MockAdPerformanceDirectory},
    IntegrationDomain.MARKETPLACES: {ProviderKind.MOCK: MockMarketplaceDirectory},
    # Los simuladores de M44 (ADR 0028): no hay todavía ningún proveedor real de pagos ni de fulfillment, y pedir
    # uno falla en vez de caer al simulado en silencio.
    IntegrationDomain.PAYMENTS: {ProviderKind.MOCK: SimulatedPaymentProvider},
    IntegrationDomain.FULFILMENT: {ProviderKind.MOCK: SimulatedFulfilmentAdapter},
}


class ProviderRegistry:
    """Resolves the active provider for each domain from Settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def kind_for(self, domain: IntegrationDomain) -> ProviderKind:
        return self._settings.provider_kinds[domain]

    def binding_for(self, domain: IntegrationDomain) -> ProviderBinding:
        kind = self.kind_for(domain)
        factory = IMPLEMENTATIONS[domain].get(kind)
        if factory is None:
            available = ", ".join(sorted(k.value for k in IMPLEMENTATIONS[domain]))
            raise ProviderNotAvailableError(
                f"no {kind} provider exists for {domain}; available: {available or 'none'}"
            )
        return ProviderBinding(
            domain=domain, kind=kind, name=factory.__name__, sources=self._sources_for(domain, kind)
        )

    def _sources_for(self, domain: IntegrationDomain, kind: ProviderKind) -> tuple[str, ...]:
        """Qué fuentes reales hay detrás, cuando hay más de una.

        Se publica para que el panel Estado pueda decir **quién** responde en vez
        de suponerlo: con dos fuentes reales, «real» a secas ya no informa."""
        if domain is not IntegrationDomain.PRODUCT_INTELLIGENCE:
            return ()
        if kind is ProviderKind.MOCK:
            return ()
        configured = tuple(self._settings.product_intelligence_real_sources)
        return configured if len(configured) > 1 else ()

    def bindings(self) -> list[ProviderBinding]:
        return [self.binding_for(domain) for domain in IntegrationDomain]

    def resolve(self, domain: IntegrationDomain, *, meter: CallMeter | None = None) -> object:
        """El proveedor activo de un dominio.

        `meter` es el contador de llamadas externas (Milestone 37, plan §25). Lo
        inyecta quien tenga sesión de base de datos y `correlation_id` —el
        servicio, no el agente—, porque un gasto sin ejecución a la que atribuirlo
        no se puede auditar. Sin contador se usa `UnmeteredCalls`, que es lo
        correcto en una prueba de unidad y lo que un montaje real no debe hacer:
        hay un test que comprueba que el camino de producción sí lo inyecta.
        """
        kind = self.kind_for(domain)
        factory = IMPLEMENTATIONS[domain].get(kind)
        if factory is None:
            available = ", ".join(sorted(k.value for k in IMPLEMENTATIONS[domain]))
            raise ProviderNotAvailableError(
                f"no {kind} provider exists for {domain}; available: {available or 'none'}"
            )
        # Un adaptador con ajustes se construye con **estos** settings, no con
        # los globales: si no, un registro creado con otra configuración
        # devolvería un proveedor que no la respeta (Milestone 34).
        builder = BUILDERS.get((domain, kind))
        if builder is not None:
            return builder(self._settings, meter or UnmeteredCalls())
        return factory()

    def simulated_domains(self) -> list[IntegrationDomain]:
        """Domains that may serve fixture data. Reads the configured kind
        rather than the resolved binding, so it still answers when some other
        domain points at an adapter that has not been built yet.

        `COMPOSITE` entra aquí: rellena con fixtures lo que la fuente real no
        da, así que un entorno que no admite datos simulados tampoco lo admite
        a él (Milestone 34). Donde importa se usa `real`, y lo que la fuente
        real no sabe queda ausente en vez de inventado."""
        return [
            domain
            for domain in IntegrationDomain
            if self.kind_for(domain) in (ProviderKind.MOCK, ProviderKind.COMPOSITE)
        ]

    def missing_implementations(self) -> list[IntegrationDomain]:
        """Domains configured to use a provider that does not exist yet."""
        return [
            domain
            for domain in IntegrationDomain
            if IMPLEMENTATIONS[domain].get(self.kind_for(domain)) is None
        ]

    def validate_for_startup(self) -> None:
        """Refuses to start on the wrong data.

        Two separate failures, reported separately so one cannot hide the
        other: an enforcing environment still on fixtures, and any environment
        pointing at an adapter nobody has written. Checked at boot rather than
        at the first call — a process that discovers halfway through a pipeline
        that it was serving invented supplier prices has already done the
        damage.
        """
        if not self._settings.allows_simulated_providers:
            simulated = self.simulated_domains()
            if simulated:
                names = ", ".join(sorted(domain.value for domain in simulated))
                raise RuntimeError(
                    f"{self._settings.environment} cannot run on simulated data; "
                    f"still on a mock provider: {names}"
                )

        missing = self.missing_implementations()
        if missing:
            names = ", ".join(f"{domain.value}={self.kind_for(domain).value}" for domain in sorted(missing))
            raise ProviderNotAvailableError(f"configured providers that do not exist yet: {names}")


def validate_providers(settings: Settings | None = None) -> None:
    ProviderRegistry(settings).validate_for_startup()
