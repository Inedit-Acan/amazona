"""Qué se puede hacer con el dato de cada proveedor (Milestone 37, ADR 0015).

La propiedad que estos tests protegen es una sola: **lo que no se sabe, no se
permite**. Todo lo demás son consecuencias de eso.
"""

import datetime

import pytest

from app.integrations.product_intelligence.ebay import PROVIDER_NAME as EBAY
from app.integrations.product_intelligence.mock import PROVIDER_NAME as FIXTURES
from app.integrations.product_intelligence.wikimedia import PROVIDER_NAME as WIKIMEDIA
from app.integrations.registry import REAL_PRODUCT_INTELLIGENCE_SOURCES
from app.integrations.usage_rights import (
    USAGE_RIGHTS,
    AttributionRequirement,
    RightStatus,
    UsageRight,
    permits,
    rights_for,
)


def test_an_unknown_right_is_not_a_permission():
    """La regla entera del módulo, en una línea."""
    rights = rights_for(EBAY)

    assert rights.status_of(UsageRight.STORAGE) is RightStatus.UNKNOWN
    assert not rights.permits(UsageRight.STORAGE)


def test_a_provider_nobody_wrote_down_has_no_rights_at_all():
    for right in UsageRight:
        assert not permits("un-proveedor-que-nadie-ha-leido", right)


def test_the_unregistered_provider_is_not_confused_with_a_denial():
    """`UNKNOWN` y `DENIED` pesan igual para actuar y no para resolver: uno está
    cerrado y el otro está por leer."""
    rights = rights_for("un-proveedor-que-nadie-ha-leido")

    assert all(rights.status_of(right) is RightStatus.UNKNOWN for right in UsageRight)
    assert rights.unresolved == sorted(UsageRight, key=lambda right: right.value)


def test_wikimedia_may_be_stored_and_scored():
    """Si esto dejara de ser cierto, el Milestone 34 se quedaría sin persistir
    nada: es la fuente real que ya está conectada."""
    assert permits(WIKIMEDIA, UsageRight.STORAGE)
    assert permits(WIKIMEDIA, UsageRight.SCORING)
    assert permits(WIKIMEDIA, UsageRight.TRANSFORMATION)


def test_wikimedia_requires_attribution_because_cc_by_sa_does():
    rights = rights_for(WIKIMEDIA)

    assert rights.attribution is AttributionRequirement.REQUIRED
    assert rights.attribution_required


def test_feeding_wikimedia_to_a_language_model_is_not_settled():
    """CC-BY-SA no lo aborda, y no decir nada no es autorizar. Afecta al plan
    maestro §26 el día que un LLM resuma estas señales."""
    assert rights_for(WIKIMEDIA).status_of(UsageRight.AI_INGESTION) is RightStatus.UNKNOWN
    assert not permits(WIKIMEDIA, UsageRight.AI_INGESTION)


def test_ebay_is_almost_entirely_unresolved():
    """No es pereza: su contrato define «Restricted APIs» por lo que la API
    aporta, y no se ha podido determinar si Browse entra ahí."""
    rights = rights_for(EBAY)

    assert UsageRight.STORAGE in rights.unresolved
    assert UsageRight.SCORING in rights.unresolved
    assert UsageRight.AI_INGESTION in rights.unresolved


def test_ebay_redistribution_is_closed_not_merely_unread():
    rights = rights_for(EBAY)

    assert rights.status_of(UsageRight.REDISTRIBUTION) is RightStatus.DENIED
    assert UsageRight.REDISTRIBUTION not in rights.unresolved


def test_attribution_is_required_while_it_is_unknown():
    """Es un deber, no un permiso: lo conservador aquí es citar, no abstenerse."""
    assert rights_for(EBAY).attribution is AttributionRequirement.UNKNOWN
    assert rights_for(EBAY).attribution_required


def test_the_fixtures_provider_owes_nobody_anything():
    """El dato es nuestro, en un fichero del repositorio. Lo que impide que
    contamine una decisión es su base SIMULATED, no su licencia."""
    assert all(permits(FIXTURES, right) for right in UsageRight)
    assert not rights_for(FIXTURES).attribution_required


@pytest.mark.parametrize("provider", sorted(REAL_PRODUCT_INTELLIGENCE_SOURCES))
def test_every_real_adapter_has_its_licence_written_down(provider):
    """El trinquete: un adaptador real nuevo no puede entrar sin que alguien haya
    leído su licencia. Si esto falla, falta una fila en la matriz — no sobra un
    test."""
    assert provider in USAGE_RIGHTS, f"{provider} no tiene derechos de uso escritos"


@pytest.mark.parametrize("provider", sorted(USAGE_RIGHTS))
def test_every_entry_says_where_and_when_it_was_read(provider):
    """Una matriz sin fuente y sin fecha es una opinión."""
    rights = USAGE_RIGHTS[provider]

    assert rights.source
    assert isinstance(rights.verified_on, datetime.date)


@pytest.mark.parametrize("provider", sorted(USAGE_RIGHTS))
def test_every_unresolved_right_says_why_or_is_simply_absent(provider):
    """No se exige una nota por cada hueco, pero las que hay tienen que
    corresponder a derechos que existen."""
    rights = USAGE_RIGHTS[provider]

    assert set(rights.notes) <= set(UsageRight)
