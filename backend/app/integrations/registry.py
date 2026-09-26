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

from app.ai.mock_ad_performance_directory import MockAdPerformanceDirectory
from app.ai.mock_marketplace_directory import MockMarketplaceDirectory
from app.ai.mock_regulatory_directory import MockRegulatoryDirectory
from app.ai.mock_supplier_directory import MockSupplierDirectory
from app.core.config import Settings, get_settings
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.product_intelligence import (
    CompositeProductSignalProvider,
    MockProductSignalProvider,
    WikimediaPageviewsProvider,
)


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
def _wikimedia_provider(settings: Settings) -> WikimediaPageviewsProvider:
    return WikimediaPageviewsProvider(
        months=settings.wikimedia_months,
        max_requests=settings.wikimedia_max_requests,
        timeout=settings.wikimedia_timeout_seconds,
    )


def _composite_product_intelligence(settings: Settings) -> CompositeProductSignalProvider:
    """Lo real primero, el relleno después (ADR 0008 y ADR 0012)."""
    return CompositeProductSignalProvider(
        [_wikimedia_provider(settings), MockProductSignalProvider()]
    )


#: Adaptadores que necesitan configuración para construirse. Se mantienen aparte
#: de `IMPLEMENTATIONS` —que sigue siendo quien dice si un proveedor existe y
#: cómo se llama— para que el nombre que aparece en el panel siga siendo el de
#: la clase y no el de una función de fábrica.
BUILDERS: dict[tuple[IntegrationDomain, ProviderKind], Callable[[Settings], object]] = {
    (IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.REAL): _wikimedia_provider,
    (IntegrationDomain.PRODUCT_INTELLIGENCE, ProviderKind.COMPOSITE): _composite_product_intelligence,
}


#: Qué implementación existe para cada dominio y tipo, y cómo se llama. Las que
#: necesitan configuración se construyen en `BUILDERS`; aquí figuran por su
#: clase, que es el nombre que el panel enseña.
IMPLEMENTATIONS: dict[IntegrationDomain, dict[ProviderKind, Callable[..., object]]] = {
    IntegrationDomain.PRODUCT_INTELLIGENCE: {
        ProviderKind.MOCK: MockProductSignalProvider,
        ProviderKind.REAL: WikimediaPageviewsProvider,
        ProviderKind.COMPOSITE: CompositeProductSignalProvider,
    },
    IntegrationDomain.SUPPLIERS: {ProviderKind.MOCK: MockSupplierDirectory},
    IntegrationDomain.REGULATORY: {ProviderKind.MOCK: MockRegulatoryDirectory},
    IntegrationDomain.ADS: {ProviderKind.MOCK: MockAdPerformanceDirectory},
    IntegrationDomain.MARKETPLACES: {ProviderKind.MOCK: MockMarketplaceDirectory},
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
        return ProviderBinding(domain=domain, kind=kind, name=factory.__name__)

    def bindings(self) -> list[ProviderBinding]:
        return [self.binding_for(domain) for domain in IntegrationDomain]

    def resolve(self, domain: IntegrationDomain) -> object:
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
            return builder(self._settings)
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
