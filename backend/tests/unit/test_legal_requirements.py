"""Las reglas de Legal del Milestone 41 (ADR 0019), como una tabla de casos.

Lo que se protege aquí es la separación entre **aplicabilidad** (la declara una
persona), **existencia y vigencia** (la verifica la fuente) y **evidencia de
cumplimiento**: ninguna se rellena con otra, y `UNKNOWN` jamás asciende a `PASS`.
"""

import datetime

import pytest

from app.core.errors import ValidationError
from app.legal.requirements import (
    INSUFFICIENT_DATA_CONFIDENCE,
    LEGAL_CONFIDENCE_CEILING,
    ActType,
    AnchorState,
    Compliance,
    ComplianceEvidenceItem,
    DeclaredRequirement,
    Existence,
    LegalStatus,
    RequirementAssessment,
    RequirementKind,
    assess_requirement,
    assess_scope,
    existence_of,
)
from app.sourcing.provenance import MissingVerifierError, SupplierFactProvenance

NOW = datetime.datetime(2026, 9, 29, 12, 0, tzinfo=datetime.UTC)
DECLARED = SupplierFactProvenance.DECLARED
VERIFIED = SupplierFactProvenance.THIRD_PARTY_VERIFIED


def requirement(**overrides) -> DeclaredRequirement:
    fields = {
        "id": "req-1",
        "product_scope": "toys",
        "jurisdiction": "eu",
        "celex": "32023R0988",
        "regulation": "General Product Safety Regulation",
        "requirement": "A safety assessment must exist",
        "kind": RequirementKind.OBLIGATION,
        "applicability_provenance": DECLARED,
        "declared_by": "owner@amazona.local",
    }
    fields.update(overrides)
    return DeclaredRequirement(**fields)


def anchor(**overrides) -> AnchorState:
    fields = {
        "found": True,
        "in_force": True,
        "act_type": ActType.REGULATION,
        "verified_at": NOW - datetime.timedelta(days=1),
        "recheck_after": NOW + datetime.timedelta(days=29),
        "source": "eur-lex-cellar",
        "source_effective_from": ("2024-12-13",),
        "source_effective_to": "9999-12-31",
    }
    fields.update(overrides)
    return AnchorState(**fields)


def evidence(provenance=DECLARED, **overrides) -> ComplianceEvidenceItem:
    fields = {"provenance": provenance, "declared_by": "owner@amazona.local"}
    if provenance is VERIFIED:
        fields["source"] = "Notified Body 0123"
    fields.update(overrides)
    return ComplianceEvidenceItem(**fields)


def assess(req=None, state="default", proofs=None) -> RequirementAssessment:
    return assess_requirement(
        req or requirement(),
        anchor() if state == "default" else state,
        [evidence()] if proofs is None else proofs,
        now=NOW,
    )


# --- PASS: lo declarado, comprobado y cubierto -------------------------------


def test_a_verified_regulation_with_evidence_passes():
    result = assess()

    assert result.status is LegalStatus.PASS
    assert result.existence is Existence.VERIFIED_IN_FORCE
    assert result.compliance is Compliance.DECLARED


def test_pass_never_claims_the_product_is_legal():
    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[assess()])

    assert scope.status is LegalStatus.PASS
    text = " ".join(scope.reasons).lower()
    assert "not a statement that the product is legal" in text
    assert "complete compliance" not in text
    assert "100" not in text


def test_pass_needs_every_declared_requirement_to_pass():
    weak = assess(requirement(id="req-2", celex="32011L0065"), proofs=[])

    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[assess(), weak])

    assert scope.status is LegalStatus.REVIEW_REQUIRED


# --- UNKNOWN: nadie ha dicho nada --------------------------------------------


def test_nothing_declared_is_unknown_and_never_pass():
    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[])

    assert scope.status is LegalStatus.UNKNOWN
    assert "not the same as there being none" in scope.reasons[0]


def test_a_jurisdiction_no_source_covers_is_unknown_even_with_declarations():
    """EUR-Lex publica Derecho de la UE: para `es` o `us` no hay fuente."""
    for jurisdiction in ("es", "us", "mx"):
        scope = assess_scope(jurisdiction=jurisdiction, scope="toys", assessments=[assess()])
        assert scope.status is LegalStatus.UNKNOWN


def test_unknown_carries_the_existing_insufficient_data_confidence():
    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[])

    assert scope.confidence == INSUFFICIENT_DATA_CONFIDENCE


# --- El principio: tres cuestiones separadas ----------------------------------


def test_evidence_of_compliance_does_not_verify_the_regulation_exists():
    """Tener el certificado no dice que la norma exista ni esté vigente."""
    result = assess(state=None)

    assert result.existence is Existence.NEVER_CHECKED
    assert result.compliance is Compliance.DECLARED
    assert result.status is LegalStatus.REVIEW_REQUIRED


def test_a_verified_regulation_does_not_supply_the_evidence_nor_the_applicability():
    result = assess(proofs=[])

    assert result.existence is Existence.VERIFIED_IN_FORCE
    assert result.compliance is Compliance.NONE
    assert result.requirement.applicability_provenance is DECLARED
    assert result.status is LegalStatus.REVIEW_REQUIRED


# --- BLOCKED solo con norma verificada y vigente ------------------------------


def test_a_restriction_verified_in_force_without_evidence_is_blocked():
    result = assess(requirement(kind=RequirementKind.RESTRICTION), proofs=[])

    assert result.status is LegalStatus.BLOCKED


def test_a_restriction_with_evidence_is_not_blocked():
    result = assess(requirement(kind=RequirementKind.RESTRICTION))

    assert result.status is LegalStatus.PASS


@pytest.mark.parametrize(
    "state",
    [
        None,
        anchor(found=False),
        anchor(in_force=None),
        anchor(in_force=False),
        anchor(recheck_after=NOW - datetime.timedelta(days=1)),
    ],
    ids=["never checked", "not found", "in-force not stated", "not in force", "stale"],
)
def test_a_restriction_is_never_blocked_on_a_regulation_that_is_not_verified(state):
    """No se bloquea con una norma que nadie ha podido confirmar: eso sería un
    resultado negativo construido sobre una duda."""
    result = assess(requirement(kind=RequirementKind.RESTRICTION), state=state, proofs=[])

    assert result.status is LegalStatus.REVIEW_REQUIRED


def test_an_expired_evidence_stops_counting():
    result = assess(
        requirement(kind=RequirementKind.RESTRICTION),
        proofs=[evidence(valid_until=datetime.date(2026, 1, 1))],
    )

    assert result.compliance is Compliance.EXPIRED
    assert result.status is LegalStatus.BLOCKED


# --- Existencia: el recheck es política nuestra, no un plazo jurídico ---------


def test_a_stale_anchor_asks_for_review_and_says_it_is_not_a_legal_conclusion():
    result = assess(state=anchor(recheck_after=NOW - datetime.timedelta(days=1)))

    assert result.existence is Existence.STALE
    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "not a statement that the regulation stopped being in force" in result.reasons[0]


def test_existence_is_decided_only_by_the_source_flag_and_the_recheck_policy():
    assert existence_of(anchor(), NOW) is Existence.VERIFIED_IN_FORCE
    assert existence_of(anchor(in_force=False), NOW) is Existence.VERIFIED_NOT_IN_FORCE
    assert existence_of(None, NOW) is Existence.NEVER_CHECKED


def test_the_9999_sentinel_is_shown_raw_and_never_interpreted_as_a_legal_fact():
    """Un fin de validez en el futuro no dice nada; `9999-12-31` no se traduce a
    «sin fin» ni se trata como una fecha real ya vencida."""
    state = anchor(source_effective_to="9999-12-31")

    assert existence_of(state, NOW) is Existence.VERIFIED_IN_FORCE
    assert state.source_effective_to == "9999-12-31"


def test_a_source_that_contradicts_itself_asks_for_review():
    state = anchor(source_effective_to="2020-01-01")

    result = assess(state=state)

    assert result.existence is Existence.SOURCE_INCONSISTENT
    assert result.status is LegalStatus.REVIEW_REQUIRED


def test_several_entry_into_force_dates_are_kept_and_none_is_chosen():
    state = anchor(source_effective_from=("2014-04-18", "2016-04-20"))

    assert state.source_effective_from == ("2014-04-18", "2016-04-20")


# --- Directivas: el acto de la UE no es la ley nacional -----------------------


def test_a_directive_alone_cannot_pass_even_with_evidence():
    result = assess(state=anchor(act_type=ActType.DIRECTIVE))

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "national transposition" in result.reasons[0]
    assert "PASS cannot be concluded" in result.reasons[0]


def test_a_restriction_under_a_directive_without_transposition_is_not_blocked():
    result = assess(
        requirement(kind=RequirementKind.RESTRICTION),
        state=anchor(act_type=ActType.DIRECTIVE),
        proofs=[],
    )

    assert result.status is LegalStatus.REVIEW_REQUIRED


def test_a_directive_with_a_declared_transposition_and_evidence_passes():
    req = requirement(
        transposition_reference="Real Decreto 187/2016",
        transposition_provenance=DECLARED,
    )

    result = assess(req, state=anchor(act_type=ActType.DIRECTIVE))

    assert result.status is LegalStatus.PASS


@pytest.mark.parametrize("act_type", [ActType.OTHER, ActType.UNKNOWN])
def test_an_act_the_source_does_not_establish_as_applicable_asks_for_review(act_type):
    result = assess(state=anchor(act_type=act_type))

    assert result.status is LegalStatus.REVIEW_REQUIRED


# --- Procedencia: quién sostiene cada hecho ----------------------------------


def test_third_party_verified_without_an_issuer_fails_at_construction():
    with pytest.raises(MissingVerifierError):
        requirement(applicability_provenance=VERIFIED)
    with pytest.raises(MissingVerifierError):
        ComplianceEvidenceItem(provenance=VERIFIED, declared_by="owner")


@pytest.mark.parametrize(
    "provenance",
    [
        SupplierFactProvenance.SIMULATED,
        SupplierFactProvenance.AMAZONA_ESTIMATE,
        SupplierFactProvenance.UNKNOWN,
        SupplierFactProvenance.SUPPLIER_CLAIM,
    ],
)
def test_a_legal_fact_can_only_be_declared_or_verified_by_a_third_party(provenance):
    with pytest.raises(ValidationError):
        requirement(applicability_provenance=provenance)


def test_a_requirement_needs_a_declared_scope_and_a_declarant():
    with pytest.raises(ValidationError):
        requirement(product_scope="  ")
    with pytest.raises(ValidationError):
        requirement(declared_by="")


def test_a_transposition_reference_needs_its_provenance():
    with pytest.raises(ValidationError):
        requirement(transposition_reference="Real Decreto 187/2016")


# --- Confianza: techos internos, no calibrados -------------------------------


def test_declared_facts_cap_the_confidence_below_third_party_ones():
    assert LEGAL_CONFIDENCE_CEILING[DECLARED] < LEGAL_CONFIDENCE_CEILING[VERIFIED]


def test_the_confidence_is_the_ceiling_of_the_weakest_link():
    declared_everything = assess()
    verified_everything = assess(
        requirement(applicability_provenance=VERIFIED, applicability_source="Ministerio X"),
        proofs=[evidence(VERIFIED)],
    )

    assert declared_everything.confidence == LEGAL_CONFIDENCE_CEILING[DECLARED]
    assert declared_everything.weakest_link is DECLARED
    assert verified_everything.confidence == LEGAL_CONFIDENCE_CEILING[VERIFIED]


def test_a_regulation_nobody_could_check_rests_on_what_was_declared():
    result = assess(
        requirement(applicability_provenance=VERIFIED, applicability_source="Ministerio X"),
        state=None,
        proofs=[evidence(VERIFIED)],
    )

    assert result.weakest_link is DECLARED


def test_an_assessment_above_its_ceiling_cannot_be_built():
    ok = assess()

    with pytest.raises(ValidationError):
        RequirementAssessment(
            requirement=ok.requirement,
            status=LegalStatus.PASS,
            reasons=(),
            existence=ok.existence,
            compliance=ok.compliance,
            anchor=ok.anchor,
            confidence=0.95,
            weakest_link=DECLARED,
        )


def test_the_scope_confidence_is_that_of_its_weakest_requirement():
    strong = assess(
        requirement(applicability_provenance=VERIFIED, applicability_source="Ministerio X"),
        proofs=[evidence(VERIFIED)],
    )
    weak = assess(requirement(id="req-2", celex="32011L0065"))

    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[strong, weak])

    assert scope.confidence == LEGAL_CONFIDENCE_CEILING[DECLARED]


# --- Del estado a la recomendación --------------------------------------------


def test_status_maps_to_the_recommendation_the_action_gate_understands():
    blocked = assess(requirement(kind=RequirementKind.RESTRICTION), proofs=[])
    review = assess(proofs=[])

    assert assess_scope(jurisdiction="eu", scope="t", assessments=[assess()]).recommendation == "GO"
    assert assess_scope(jurisdiction="eu", scope="t", assessments=[review]).recommendation == "REVIEW"
    assert assess_scope(jurisdiction="eu", scope="t", assessments=[blocked]).recommendation == "NO_GO"


def test_unknown_is_review_never_no_go():
    """ADR 0018: no poder evaluar no es un resultado negativo. El ActionGate veta
    los NO_GO que gastan, y esto no es uno."""
    scope = assess_scope(jurisdiction="eu", scope="toys", assessments=[])

    assert scope.recommendation == "REVIEW"


def test_a_block_wins_over_a_review_which_wins_over_a_pass():
    passing = assess()
    review = assess(requirement(id="req-2"), proofs=[])
    blocked = assess(requirement(id="req-3", kind=RequirementKind.RESTRICTION), proofs=[])

    assert assess_scope(jurisdiction="eu", scope="t", assessments=[passing, review]).status is (
        LegalStatus.REVIEW_REQUIRED
    )
    assert assess_scope(
        jurisdiction="eu", scope="t", assessments=[passing, review, blocked]
    ).status is LegalStatus.BLOCKED
