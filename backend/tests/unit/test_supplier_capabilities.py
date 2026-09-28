"""Las ocho capacidades del plan maestro §16, con procedencia (Milestone 39)."""

import datetime

import pytest

from app.sourcing.capabilities import (
    MODEL_CRITICAL,
    CapabilityDeclaration,
    SupplyCapability,
    profile,
    resolve,
    unanswered,
)
from app.sourcing.provenance import MissingVerifierError, SupplierFactProvenance

CLAIM = SupplierFactProvenance.SUPPLIER_CLAIM
AUDIT = SupplierFactProvenance.THIRD_PARTY_VERIFIED


def declaration(capability, supported, provenance=CLAIM, **kwargs):
    kwargs.setdefault("source", "auditor" if provenance is AUDIT else "correo del comercial")
    return CapabilityDeclaration(
        capability=capability, supported=supported, provenance=provenance, **kwargs
    )


def test_the_eight_capabilities_of_the_plan_are_all_there():
    """Conjunto cerrado: añadir una es una decisión de producto, no una clave
    nueva en un diccionario."""
    assert {c.value for c in SupplyCapability} == {
        "direct_shipping",
        "dropshipping",
        "blind_shipping",
        "custom_packaging",
        "tracking",
        "returns",
        "eu_return_address",
        "sla",
    }


def test_no_declaration_means_unknown_not_false():
    """La confusión que este módulo existe para quitar: «no lo soporta» y
    «nadie lo ha preguntado» no son lo mismo."""
    answer = resolve([], SupplyCapability.DROPSHIPPING)

    assert answer.supported is None
    assert answer.provenance is SupplierFactProvenance.UNKNOWN
    assert not answer.known


def test_a_declaration_carries_who_says_so():
    answer = resolve(
        [declaration(SupplyCapability.TRACKING, True)], SupplyCapability.TRACKING
    )

    assert answer.supported is True
    assert answer.provenance is CLAIM
    assert answer.source == "correo del comercial"


def test_a_capability_cannot_be_declared_unknown():
    with pytest.raises(ValueError, match="not declaring it already says that"):
        CapabilityDeclaration(
            capability=SupplyCapability.SLA,
            supported=True,
            provenance=SupplierFactProvenance.UNKNOWN,
        )


def test_third_party_verification_needs_an_issuer():
    with pytest.raises(MissingVerifierError, match="naming the verifier"):
        CapabilityDeclaration(
            capability=SupplyCapability.SLA, supported=True, provenance=AUDIT, source="  "
        )


def test_an_audited_declaration_beats_the_suppliers_own_word():
    answers = [
        declaration(SupplyCapability.EU_RETURN_ADDRESS, True),
        declaration(SupplyCapability.EU_RETURN_ADDRESS, False, AUDIT),
    ]

    answer = resolve(answers, SupplyCapability.EU_RETURN_ADDRESS)

    assert answer.supported is False
    assert answer.provenance is AUDIT


def test_a_product_specific_declaration_overrides_the_general_one():
    """Quien se molesta en decir algo de **este** artículo está corrigiendo la
    regla de la casa, no repitiéndola — aunque la general esté auditada."""
    answers = [
        declaration(SupplyCapability.DIRECT_SHIPPING, True, AUDIT),
        declaration(SupplyCapability.DIRECT_SHIPPING, False, product_id="p-1"),
    ]

    assert resolve(answers, SupplyCapability.DIRECT_SHIPPING, product_id="p-1").supported is False
    assert resolve(answers, SupplyCapability.DIRECT_SHIPPING).supported is True


def test_a_declaration_for_another_product_does_not_apply():
    answers = [declaration(SupplyCapability.DIRECT_SHIPPING, False, product_id="p-other")]

    assert resolve(answers, SupplyCapability.DIRECT_SHIPPING, product_id="p-1").supported is None


def test_between_equals_the_more_recent_declaration_wins():
    older = declaration(
        SupplyCapability.RETURNS,
        False,
        observed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    newer = declaration(
        SupplyCapability.RETURNS,
        True,
        observed_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
    )

    assert resolve([older, newer], SupplyCapability.RETURNS).supported is True


def test_a_declaration_without_a_date_is_treated_as_the_oldest():
    """No consta que sea de ayer, así que no se le da la razón sobre una fechada."""
    undated = declaration(SupplyCapability.RETURNS, False)
    dated = declaration(
        SupplyCapability.RETURNS,
        True,
        observed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )

    assert resolve([undated, dated], SupplyCapability.RETURNS).supported is True


def test_the_profile_always_returns_all_eight():
    """Una lista corta dejaría al que la lee sin saber si falta una capacidad
    porque no se soporta o porque nadie la preguntó."""
    answers = profile([declaration(SupplyCapability.TRACKING, True)])

    assert len(answers) == len(SupplyCapability)
    assert [a.capability for a in answers] == list(SupplyCapability)


def test_unanswered_lists_what_still_has_to_be_asked():
    declared = [declaration(c, True) for c in MODEL_CRITICAL[:2]]

    missing = unanswered(declared)

    assert set(missing) == set(MODEL_CRITICAL[2:])


def test_a_declared_no_counts_as_answered():
    """Vacío no significa «compatible»: significa que ya no faltan respuestas."""
    declared = [declaration(c, False) for c in MODEL_CRITICAL]

    assert unanswered(declared) == []
