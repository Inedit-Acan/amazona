"""Derechos de uso y coste de EUR-Lex/Cellar, resueltos ANTES de la primera llamada
(Milestone 41, regla del M37)."""

import datetime

from app.costs.policy import Pricing, policy_for
from app.integrations.regulatory.eur_lex import PROVIDER_NAME
from app.integrations.usage_rights import USAGE_RIGHTS, UsageRight, permits, rights_for


def test_the_source_has_its_licence_written_down():
    assert PROVIDER_NAME in USAGE_RIGHTS


def test_the_licence_was_read_where_and_when_it_says():
    rights = rights_for(PROVIDER_NAME)

    assert "eur-lex.europa.eu/content/legal-notice" in rights.source
    assert rights.verified_on == datetime.date(2026, 9, 29)


def test_what_is_stored_may_be_stored_and_retained():
    """Metadatos CC0: existencia, vigencia, fechas. Ni texto ni traducciones."""
    assert permits(PROVIDER_NAME, UsageRight.STORAGE)
    assert permits(PROVIDER_NAME, UsageRight.RETENTION)


def test_no_right_is_left_unresolved_so_nothing_is_denied_by_silence():
    assert rights_for(PROVIDER_NAME).unresolved == []


def test_the_storage_note_says_only_metadata_is_stored():
    assert "metadatos" in rights_for(PROVIDER_NAME).notes[UsageRight.STORAGE].lower()


def test_the_source_is_free_but_its_quota_is_unknown_not_unlimited():
    policy = policy_for(PROVIDER_NAME)

    assert policy.pricing is Pricing.FREE
    assert policy.cost_per_unit == 0.0
    # No se ha encontrado una cuota publicada: «no sé» no es «sin límite», y por
    # eso hay un tope por ejecución propio.
    assert policy.quota_units_per_day is None
    assert policy.max_units_per_run is not None


def test_the_cost_policy_says_where_its_numbers_come_from():
    assert policy_for(PROVIDER_NAME).source
