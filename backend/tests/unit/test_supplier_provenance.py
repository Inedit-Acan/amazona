"""Quién sostiene un hecho sobre un proveedor (Milestone 39, ADR 0017)."""

import pytest

from app.sourcing.provenance import (
    STORABLE,
    Fact,
    MissingVerifierError,
    SupplierFactProvenance,
    best,
    parse,
    rank,
)


def test_a_value_must_say_who_says_so():
    """Un número sin autor es lo que este milestone quita de en medio."""
    with pytest.raises(ValueError, match="who says so"):
        Fact(value=4.2, provenance=SupplierFactProvenance.UNKNOWN)


def test_an_absent_fact_cannot_have_a_provenance():
    with pytest.raises(ValueError, match="no source to attribute"):
        Fact(value=None, provenance=SupplierFactProvenance.SUPPLIER_CLAIM)


def test_third_party_verification_without_an_issuer_fails_loudly():
    """«Verificado» sin decir por quién no explica nada (plan maestro §10), y
    falla al construir en vez de recortarse en silencio."""
    with pytest.raises(MissingVerifierError, match="name the verifier"):
        Fact(value=True, provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED)


def test_third_party_verification_with_an_issuer_is_accepted():
    fact = Fact(
        value=True,
        provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED,
        source="Bureau of Test",
    )
    assert fact.known


def test_unknown_is_not_storable():
    """Una fila que dice «no se sabe» afirma lo mismo que no tener fila, y
    además es indistinguible de un error de carga."""
    assert SupplierFactProvenance.UNKNOWN not in STORABLE
    assert len(STORABLE) == len(SupplierFactProvenance) - 1


def test_an_absent_column_reads_as_unknown_not_as_a_negative():
    assert parse(None) is SupplierFactProvenance.UNKNOWN
    assert parse("") is SupplierFactProvenance.UNKNOWN


def test_a_corrupt_value_is_not_quietly_read_as_unknown():
    """Convertir un error de datos en «no se sabe» sería una respuesta
    tranquilizadora sobre una fila rota."""
    with pytest.raises(ValueError):
        parse("verified-ish")


def test_third_party_beats_supplier_claim_beats_estimate_beats_fixture():
    order = [
        SupplierFactProvenance.THIRD_PARTY_VERIFIED,
        SupplierFactProvenance.SUPPLIER_CLAIM,
        SupplierFactProvenance.AMAZONA_ESTIMATE,
        SupplierFactProvenance.SIMULATED,
        SupplierFactProvenance.UNKNOWN,
    ]
    assert [rank(p) for p in order] == sorted(rank(p) for p in order)


def test_best_prefers_the_stronger_provenance():
    claim = Fact(value=4.2, provenance=SupplierFactProvenance.SUPPLIER_CLAIM, source="mail")
    audited = Fact(
        value=4.9, provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED, source="auditor"
    )
    assert best([claim, audited]) is audited


def test_best_of_nothing_known_is_unknown_not_the_first_one():
    assert best([Fact.unknown(), Fact.unknown()]).provenance is SupplierFactProvenance.UNKNOWN


def test_best_is_stable_between_equals():
    first = Fact(value=1.0, provenance=SupplierFactProvenance.SUPPLIER_CLAIM, source="a")
    second = Fact(value=2.0, provenance=SupplierFactProvenance.SUPPLIER_CLAIM, source="b")
    assert best([first, second]) is first
