"""Milestone 30: which provider is active, and where fixtures are refused."""

import pytest

from app.agents.legal_compliance import LegalComplianceAgent
from app.agents.marketing_campaign import MarketingCampaignAgent
from app.agents.marketplace_listing import MarketplaceListingAgent
from app.agents.product_research import ProductResearchAgent
from app.agents.supplier_sourcing import SupplierSourcingAgent
from app.core.config import Environment, Settings, WikimediaSettings
from app.integrations.ports import PORT_FOR_DOMAIN, IntegrationDomain, ProviderKind
from app.integrations.registry import (
    IMPLEMENTATIONS,
    ProviderNotAvailableError,
    ProviderRegistry,
    validate_providers,
)

CONFIGURED = {"supabase_url": "https://example.supabase.co", "supabase_anon_key": "anon-key"}


def settings_for(environment: Environment, **overrides) -> Settings:
    return Settings(_env_file=None, environment=environment, **overrides)


def test_every_domain_has_a_declared_port():
    assert set(PORT_FOR_DOMAIN) == set(IntegrationDomain)


def test_every_domain_has_at_least_a_mock_implementation():
    for domain in IntegrationDomain:
        assert ProviderKind.MOCK in IMPLEMENTATIONS[domain], domain


def test_development_resolves_to_the_mock_provider():
    registry = ProviderRegistry(settings_for(Environment.DEVELOPMENT))

    bindings = {b.domain: b for b in registry.bindings()}
    assert set(bindings) == set(IntegrationDomain)
    for binding in bindings.values():
        assert binding.kind is ProviderKind.MOCK
        assert binding.is_simulated is True
        # Los fixtures de datos se llaman `Mock…`; los simuladores de acciones de M44, `Simulated…`.
        assert binding.name.startswith(("Mock", "Simulated"))


def test_a_provider_that_does_not_exist_yet_is_an_error_not_a_fallback():
    """The dangerous failure mode is asking for real data and quietly getting
    fixtures, so an unbuilt adapter raises."""
    registry = ProviderRegistry(
        settings_for(Environment.DEVELOPMENT, suppliers_provider=ProviderKind.REAL)
    )

    with pytest.raises(ProviderNotAvailableError, match="no real provider exists for suppliers"):
        registry.resolve(IntegrationDomain.SUPPLIERS)


# --- Criterios de aceptación del plan maestro --------------------------------


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_enforcing_environments_refuse_to_start_on_mock_data(environment: Environment):
    settings = settings_for(environment, cors_origins=["https://kova.example"], **CONFIGURED)

    with pytest.raises(RuntimeError) as error:
        validate_providers(settings)

    message = str(error.value)
    # The three the plan maestro names by hand, plus the two it does not, plus the two M44 adds.
    for domain in ("product_intelligence", "suppliers", "regulatory", "ads", "marketplaces", "payments", "fulfilment"):
        assert domain in message


def test_production_still_refuses_when_only_one_domain_is_simulated():
    """Partial progress is not progress: one mock left is still a mock in
    production."""
    settings = settings_for(
        Environment.PRODUCTION,
        cors_origins=["https://kova.example"],
        product_intelligence_provider=ProviderKind.SANDBOX,
        suppliers_provider=ProviderKind.SANDBOX,
        regulatory_provider=ProviderKind.SANDBOX,
        ads_provider=ProviderKind.SANDBOX,
        **CONFIGURED,
    )

    with pytest.raises(RuntimeError, match="marketplaces"):
        validate_providers(settings)


@pytest.mark.parametrize(
    "environment", [Environment.DEVELOPMENT, Environment.TEST, Environment.DEMO]
)
def test_local_environments_may_run_on_mock_data(environment: Environment):
    validate_providers(settings_for(environment))


def test_a_production_asking_for_real_data_is_no_longer_simulated_but_still_cannot_start():
    """El estado honesto del proyecto: desde el Milestone 34 existe un adaptador
    real para Product Intelligence, y para los otros seis dominios todavía no.
    Una producción configurada entera en real deja de ser simulada y falla por
    el motivo correcto: nadie ha escrito esos seis."""
    settings = settings_for(
        Environment.PRODUCTION,
        cors_origins=["https://kova.example"],
        product_intelligence_provider=ProviderKind.REAL,
        suppliers_provider=ProviderKind.REAL,
        regulatory_provider=ProviderKind.REAL,
        ads_provider=ProviderKind.REAL,
        marketplaces_provider=ProviderKind.REAL,
        payments_provider=ProviderKind.REAL,
        fulfilment_provider=ProviderKind.REAL,
        **CONFIGURED,
    )

    assert ProviderRegistry(settings).simulated_domains() == []
    with pytest.raises(ProviderNotAvailableError, match="do not exist yet"):
        validate_providers(settings)


def test_a_missing_adapter_fails_even_in_development():
    """Pointing at an adapter nobody wrote is a configuration error anywhere,
    not only in production."""
    settings = settings_for(Environment.DEVELOPMENT, ads_provider=ProviderKind.SANDBOX)

    with pytest.raises(ProviderNotAvailableError, match="ads=sandbox"):
        validate_providers(settings)


# --- Los agentes ya no conocen a su mock -------------------------------------


@pytest.mark.parametrize(
    ("agent_class", "attribute"),
    [
        (ProductResearchAgent, "_trends"),
        (SupplierSourcingAgent, "_directory"),
        (LegalComplianceAgent, "_directory"),
        (MarketingCampaignAgent, "_directory"),
        (MarketplaceListingAgent, "_directory"),
    ],
)
def test_an_agent_takes_its_provider_from_the_registry(agent_class, attribute):
    agent = agent_class()

    assert type(getattr(agent, attribute)).__name__.startswith("Mock")


@pytest.mark.parametrize(
    ("agent_class", "attribute"),
    [
        (ProductResearchAgent, "_trends"),
        (SupplierSourcingAgent, "_directory"),
        (LegalComplianceAgent, "_directory"),
        (MarketingCampaignAgent, "_directory"),
        (MarketplaceListingAgent, "_directory"),
    ],
)
def test_an_injected_provider_still_wins(agent_class, attribute):
    """Injection is how tests and future adapters replace a provider; the
    registry is only the default."""
    sentinel = object()

    agent = agent_class(sentinel)

    assert getattr(agent, attribute) is sentinel

# --- El primer adaptador real (Milestone 34) --------------------------------


def test_product_intelligence_has_a_real_adapter_now():
    """Deja de ser cierto que ningún dominio tenga adaptador real."""
    from app.integrations.product_intelligence import WikimediaPageviewsProvider

    settings = settings_for(
        Environment.DEVELOPMENT, product_intelligence_provider=ProviderKind.REAL
    )

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert isinstance(provider, WikimediaPageviewsProvider)
    assert ProviderRegistry(settings).simulated_domains() == [
        IntegrationDomain.SUPPLIERS,
        IntegrationDomain.REGULATORY,
        IntegrationDomain.ADS,
        IntegrationDomain.MARKETPLACES,
        IntegrationDomain.PAYMENTS,
        IntegrationDomain.FULFILMENT,
    ]


def test_the_real_adapter_takes_its_limits_from_configuration():
    """El tope de peticiones no es un número escondido en el adaptador: existe
    por el arriendo del runtime y se configura (ADR 0009, ADR 0012)."""
    settings = settings_for(
        Environment.DEVELOPMENT,
        product_intelligence_provider=ProviderKind.REAL,
        # Milestone 37: los ajustes de cada adaptador viven en su propio espacio
        # de nombres, no sueltos en el objeto de configuración.
        wikimedia=WikimediaSettings(max_requests=3, months=6),
    )

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert provider._max_requests == 3
    assert provider._months == 6


def test_a_composite_counts_as_simulated_because_it_can_serve_fixtures():
    """Aunque la mayoría de sus señales sean reales, puede rellenar con
    fixtures: un panel que dijera «real» mentiría en la parte que importa."""
    settings = settings_for(
        Environment.DEVELOPMENT, product_intelligence_provider=ProviderKind.COMPOSITE
    )
    registry = ProviderRegistry(settings)

    assert IntegrationDomain.PRODUCT_INTELLIGENCE in registry.simulated_domains()
    assert registry.binding_for(IntegrationDomain.PRODUCT_INTELLIGENCE).is_simulated is True


def test_an_enforcing_environment_refuses_a_composite():
    """Lo que no se admite es servir datos inventados donde se toman decisiones
    reales; que vengan mezclados con reales no lo hace admisible."""
    settings = settings_for(
        Environment.PRODUCTION,
        cors_origins=["https://kova.example"],
        product_intelligence_provider=ProviderKind.COMPOSITE,
        **CONFIGURED,
    )

    with pytest.raises(RuntimeError, match="cannot run on simulated data"):
        validate_providers(settings)


def test_a_composite_resolves_to_the_real_source_first():
    from app.integrations.product_intelligence import (
        CompositeProductSignalProvider,
        MockProductSignalProvider,
        WikimediaPageviewsProvider,
    )

    settings = settings_for(
        Environment.DEVELOPMENT, product_intelligence_provider=ProviderKind.COMPOSITE
    )

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert isinstance(provider, CompositeProductSignalProvider)
    assert isinstance(provider._providers[0], WikimediaPageviewsProvider)
    assert isinstance(provider._providers[1], MockProductSignalProvider)
