"""Que el camino real vaya con contador (Milestone 37, plan maestro §25).

`UnmeteredCalls` existe para probar un adaptador en aislamiento, y si acabara en
producción las llamadas externas se harían sin techo y sin registro. Esto es el
trinquete que lo impide: comprueba que quien monta un proveedor de verdad le pasa
un contador de verdad.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Environment, Settings
from app.costs.service import CostMeter, UnmeteredCalls
from app.db.base import Base
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.registry import (
    REAL_PRODUCT_INTELLIGENCE_SOURCES,
    ProviderRegistry,
    UnknownRealSourceError,
)
from app.research import service as research_service
from app.research.service import ResearchService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def settings_for(**overrides) -> Settings:
    return Settings(_env_file=None, environment=Environment.DEVELOPMENT, **overrides)


# --- El cableado ------------------------------------------------------------


def test_the_research_service_injects_a_real_meter(db_session: Session, monkeypatch):
    """Sin agente inyectado, el servicio monta el configurado — y le pasa un
    contador atado a la ejecución, porque un gasto sin ejecución a la que
    atribuirlo no se puede auditar."""
    seen: dict[str, object] = {}
    original = research_service.ProviderRegistry.resolve

    def spy(self, domain, *, meter=None):
        seen["domain"] = domain
        seen["meter"] = meter
        return original(self, domain, meter=meter)

    monkeypatch.setattr(research_service.ProviderRegistry, "resolve", spy)
    ResearchService(db_session).run_research(
        category="home", keywords=None, max_results=1, correlation_id="cid-meter"
    )

    assert seen["domain"] is IntegrationDomain.PRODUCT_INTELLIGENCE
    assert isinstance(seen["meter"], CostMeter)


def test_an_injected_agent_still_wins(db_session: Session):
    """Es lo que permite a un test poner una fuente de mentira."""
    from app.agents.product_research import ProductResearchAgent

    agent = ProductResearchAgent()
    service = ResearchService(db_session, agent=agent)

    assert service._agent_for("cid-1") is agent


def test_resolving_without_a_meter_falls_back_to_the_unmetered_one():
    """El caso de una prueba de unidad. Documentado, no accidental."""
    settings = settings_for(product_intelligence_provider=ProviderKind.REAL)

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert provider is not None
    # El adaptador de Wikimedia no recibe contador porque no lo usa todavía; el
    # que sí lo usa es eBay, y su builder lo recibe igual.
    assert isinstance(UnmeteredCalls(), UnmeteredCalls)


# --- Varias fuentes reales --------------------------------------------------


def test_one_real_source_is_used_directly():
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["wikimedia-pageviews"],
    )

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert provider.name == "wikimedia-pageviews"


def test_two_real_sources_compose_and_are_not_simulated():
    """Lo que `real` significa con más de una fuente real (ADR 0015): un
    compuesto **entre reales**, que sirve donde los fixtures están prohibidos."""
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["wikimedia-pageviews", "ebay-browse"],
        ebay={"client_id": "id", "client_secret": "secret"},
    )
    registry = ProviderRegistry(settings)

    provider = registry.resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)
    binding = registry.binding_for(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert provider.name == "composite"
    assert not binding.is_simulated
    assert binding.sources == ("wikimedia-pageviews", "ebay-browse")


def test_a_single_source_publishes_no_list():
    """Con una sola fuente el nombre ya lo dice todo, y una lista de un elemento
    no añade nada al panel."""
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["wikimedia-pageviews"],
    )

    assert ProviderRegistry(settings).binding_for(IntegrationDomain.PRODUCT_INTELLIGENCE).sources == ()


def test_the_order_of_the_sources_is_the_configured_one():
    """El primero que da una señal manda; los siguientes rellenan (ADR 0012 §6)."""
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["ebay-browse", "wikimedia-pageviews"],
        ebay={"client_id": "id", "client_secret": "secret"},
    )

    binding = ProviderRegistry(settings).binding_for(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert binding.sources == ("ebay-browse", "wikimedia-pageviews")


def test_a_source_nobody_wrote_is_an_error_not_a_silent_omission():
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["keepa"],
    )

    with pytest.raises(UnknownRealSourceError, match="keepa"):
        ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)


def test_no_sources_at_all_is_an_error_too():
    """Un proveedor real sin fuentes no contestaría nada, y eso se leería como una
    medición de que no hay nada."""
    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=[],
    )

    with pytest.raises(UnknownRealSourceError):
        ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)


def test_composite_still_puts_the_fixtures_last():
    settings = settings_for(
        product_intelligence_provider=ProviderKind.COMPOSITE,
        product_intelligence_real_sources=["wikimedia-pageviews"],
    )

    provider = ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)

    assert [inner.name for inner in provider._providers] == ["wikimedia-pageviews", "fixtures"]


def test_configuring_ebay_without_keys_fails_at_startup(monkeypatch):
    """No en la primera búsqueda: un proceso que descubre a mitad del pipeline que
    no puede preguntar ya ha hecho el daño (ADR 0008 §4)."""
    from app.integrations.product_intelligence.ebay import EbayCredentialsMissingError

    settings = settings_for(
        product_intelligence_provider=ProviderKind.REAL,
        product_intelligence_real_sources=["ebay-browse"],
    )

    with pytest.raises(EbayCredentialsMissingError):
        ProviderRegistry(settings).resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)


def test_every_declared_source_can_actually_be_built():
    """Un nombre en la lista sin constructor detrás sería un error de arranque
    esperando a que alguien lo configure."""
    assert set(REAL_PRODUCT_INTELLIGENCE_SOURCES) == {"wikimedia-pageviews", "ebay-browse"}
