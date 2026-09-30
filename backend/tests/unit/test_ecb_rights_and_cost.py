"""Derechos de uso y coste de las referencias del BCE, resueltos ANTES de la primera
llamada (Milestone 42, regla del M37)."""

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
from app.money.ecb import ATTRIBUTION, NOTICE, PROVIDER_NAME

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

    assert "ecb.europa.eu/services/using-our-site/disclaimer" in rights.source
    assert rights.verified_on == datetime.date(2026, 9, 29)


@pytest.mark.parametrize("right", ALLOWED)
def test_the_uses_the_general_free_use_grant_covers_are_allowed(right):
    assert permits(PROVIDER_NAME, right)


def test_ai_ingestion_is_unresolved_and_therefore_denied():
    """Los términos no dicen nada: no se infiere un permiso del silencio."""
    rights = rights_for(PROVIDER_NAME)

    assert rights.status_of(UsageRight.AI_INGESTION) is RightStatus.UNKNOWN
    assert not permits(PROVIDER_NAME, UsageRight.AI_INGESTION)
    assert rights.unresolved == [UsageRight.AI_INGESTION]


def test_attribution_is_a_duty_not_a_permission():
    assert rights_for(PROVIDER_NAME).attribution is AttributionRequirement.REQUIRED
    assert rights_for(PROVIDER_NAME).attribution_required


def test_each_permission_says_why_and_admits_it_is_not_an_express_grant():
    rights = rights_for(PROVIDER_NAME)

    for right in UsageRight:
        assert rights.notes.get(right), f"{right} has no note"
    assert "no hay una cláusula específica" in rights.notes[UsageRight.STORAGE]


def test_the_source_is_free_but_its_quota_is_unknown_not_unlimited():
    policy = policy_for(PROVIDER_NAME)

    assert policy.pricing is Pricing.FREE
    assert policy.cost_per_unit == 0.0
    assert policy.quota_units_per_day is None
    assert policy.max_units_per_run == 2
    assert policy.source


def test_the_attribution_and_the_notice_say_what_the_licence_and_the_bank_require():
    assert "Banco Central Europeo" in ATTRIBUTION
    assert "no es la tasa transaccional" in NOTICE
