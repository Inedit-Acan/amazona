"""Milestone 30: which provider is active, and where fixtures are refused."""

import pytest

from app.agents.legal_compliance import LegalComplianceAgent
from app.agents.marketing_campaign import MarketingCampaignAgent
from app.agents.marketplace_listing import MarketplaceListingAgent
from app.agents.product_research import ProductResearchAgent
from app.agents.supplier_sourcing import SupplierSourcingAgent
from app.core.config import Environment, Settings
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
        assert binding.name.startswith("Mock")


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
    # The three the plan maestro names by hand, plus the two it does not.
    for domain in ("product_intelligence", "suppliers", "regulatory", "ads", "marketplaces"):
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
    """The honest state of the project today: Milestone 30 builds the mechanism,
    the real adapters arrive in Milestones 34-35. A production configured for
    real data stops being simulated and starts failing for the right reason —
    nobody has written those adapters."""
    settings = settings_for(
        Environment.PRODUCTION,
        cors_origins=["https://kova.example"],
        product_intelligence_provider=ProviderKind.REAL,
        suppliers_provider=ProviderKind.REAL,
        regulatory_provider=ProviderKind.REAL,
        ads_provider=ProviderKind.REAL,
        marketplaces_provider=ProviderKind.REAL,
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
