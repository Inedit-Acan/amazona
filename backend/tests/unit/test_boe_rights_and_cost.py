"""Derechos de uso y coste del BOE, resueltos ANTES de la primera llamada
(Milestone 43, regla del M37)."""

import datetime

import pytest

from app.costs.policy import Pricing, policy_for
from app.integrations.usage_rights import (
    USAGE_RIGHTS,
    AttributionRequirement,
    RightStatus,
    UsageRight,
    permits,
    rights_for,
)
from app.legal.national import ATTRIBUTION, NOTICE, PROVIDER_NAME

ALLOWED = [
    UsageRight.STORAGE,
    UsageRight.RETENTION,
    UsageRight.TRANSFORMATION,
    UsageRight.DERIVED_METRICS,
    UsageRight.SCORING,
    UsageRight.REDISTRIBUTION,
    UsageRight.COMMERCIAL_USE,
]


def test_the_source_has_its_licence_written_down():
    assert PROVIDER_NAME in USAGE_RIGHTS


def test_the_licence_was_read_where_and_when_it_says():
    rights = rights_for(PROVIDER_NAME)

    assert "boe.es/informacion/aviso_legal" in rights.source
    assert rights.verified_on == datetime.date(2026, 9, 29)


@pytest.mark.parametrize("right", ALLOWED)
def test_the_uses_the_general_reuse_licence_covers_are_allowed(right):
    assert permits(PROVIDER_NAME, right)


def test_ai_ingestion_is_unresolved_and_therefore_denied():
    rights = rights_for(PROVIDER_NAME)

    assert rights.status_of(UsageRight.AI_INGESTION) is RightStatus.UNKNOWN
    assert not permits(PROVIDER_NAME, UsageRight.AI_INGESTION)
    assert rights.unresolved == [UsageRight.AI_INGESTION]


def test_attribution_is_a_duty():
    assert rights_for(PROVIDER_NAME).attribution is AttributionRequirement.REQUIRED


def test_the_notes_say_the_text_is_not_stored_and_the_source_is_informational():
    rights = rights_for(PROVIDER_NAME)

    assert "texto de las normas no se guarda" in rights.notes[UsageRight.STORAGE]
    assert "meramente informativo" in rights.notes[UsageRight.REDISTRIBUTION]
    for right in UsageRight:
        assert rights.notes.get(right), f"{right} has no note"


def test_the_source_is_free_but_its_quota_is_unknown_not_unlimited():
    policy = policy_for(PROVIDER_NAME)

    assert policy.pricing is Pricing.FREE
    assert policy.cost_per_unit == 0.0
    assert policy.quota_units_per_day is None
    assert policy.max_units_per_run == 12
    assert policy.source


def test_the_required_notice_and_attribution_say_what_the_licence_requires():
    assert "meramente informativo" in NOTICE
    assert "publicación oficial" in NOTICE
    assert ATTRIBUTION == "Basado en datos de la Agencia Estatal Boletín Oficial del Estado"
