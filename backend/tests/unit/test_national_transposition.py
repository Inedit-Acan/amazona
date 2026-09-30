"""Transposiciones nacionales: corroboración y evaluación (Milestone 43, ADR 0021).

Se prueba con **respuestas reales del BOE** guardadas en `tests/fixtures/boe/`:
el Real Decreto 1205/2011 (juguetes, que el análisis del BOE declara `TRANSPONE` de la
Directiva 2009/48/CE) y la Ley 30/1992 (derogada).

Lo que se protege: la comparación con el CELEX es **determinista o no es**; un 404, un
fallo o un texto ilegible nunca son una contradicción; y `PASS` sigue exigiendo
evidencia de cumplimiento además de la corroboración.
"""

import copy
import datetime
import json
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.integrations.regulatory.boe import parse_metadata, parse_relations
from app.legal.national import (
    INFORMATIONAL_CONFIDENCE_CEILING,
    Corroboration,
    NationalAnchorState,
    NationalState,
    assess_transposition,
    corroborate,
    designations_in,
    directive_key,
    official_url,
    validate_national_id,
)
from app.legal.requirements import (
    ActType,
    AnchorState,
    ComplianceEvidenceItem,
    DeclaredRequirement,
    LegalStatus,
    RequirementKind,
    assess_requirement,
)
from app.sourcing.provenance import SupplierFactProvenance

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "boe"
NOW = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=datetime.UTC)
TOYS_ID = "BOE-A-2011-14252"
TOYS = "32009L0048"
LVD = "32014L0035"
DECLARED = SupplierFactProvenance.DECLARED
VERIFIED = SupplierFactProvenance.THIRD_PARTY_VERIFIED


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def toys_anchor(**overrides) -> NationalAnchorState:
    fields = {
        "national_id": TOYS_ID,
        "verified_at": NOW - datetime.timedelta(days=1),
        "recheck_after": NOW + datetime.timedelta(days=29),
        "consolidated": True,
        "metadata": parse_metadata(load(f"metadatos_{TOYS_ID}.json"), TOYS_ID),
        "relations": parse_relations(load(f"analisis_{TOYS_ID}.json")),
        "publication_state": "confirmed",
    }
    fields.update(overrides)
    return NationalAnchorState(**fields)


def relation(code: int, text: str, id_norma: str = "DOUE-L-2009-81173") -> dict:
    return {"id_norma": id_norma, "relation_code": code, "relation": "X", "text": text}


# --- Identificadores y designaciones -----------------------------------------


@pytest.mark.parametrize("good", ["BOE-A-2011-14252", " boe-a-1889-4763 ", "BOE-A-2015-10566"])
def test_a_boe_identifier_is_validated_before_anything_is_asked(good):
    assert validate_national_id(good).startswith("BOE-A-")


@pytest.mark.parametrize(
    "bad", ["", "BOE-A-11-1", "DOUE-L-2009-81173", "Real Decreto 1205/2011", "BOE-A-2011-14252/x", "../etc"]
)
def test_anything_else_is_refused(bad):
    with pytest.raises(ValidationError):
        validate_national_id(bad)


def test_the_official_link_is_built_from_the_identifier_alone():
    assert official_url(TOYS_ID) == "https://www.boe.es/buscar/doc.php?id=BOE-A-2011-14252"


@pytest.mark.parametrize(
    ("celex", "key"),
    [("32009L0048", (2009, 48)), ("32014L0035", (2014, 35)), ("31973L0023", (1973, 23))],
)
def test_the_year_and_number_of_a_directive_come_from_its_celex(celex, key):
    assert directive_key(celex) == key


@pytest.mark.parametrize("celex", ["32023R0988", "not-a-celex", "", "32009L48"])
def test_only_a_directive_has_a_key(celex):
    assert directive_key(celex) is None


@pytest.mark.parametrize(
    ("text", "found", "ambiguous"),
    [
        ("la Directiva 2009/48/CE, de 18 de junio de 2009", {(2009, 48)}, False),
        ("la Directiva (UE) 2015/1535 del Parlamento", {(2015, 1535)}, False),
        ("la Directiva 2014/35/UE", {(2014, 35)}, False),
        ("la Directiva 73/23/CEE", {(1973, 23)}, False),
        ("la Directiva 2014/35/UE y la Directiva 2014/30/UE", {(2014, 35), (2014, 30)}, False),
        ("las Directivas 2014/35/UE y la Directiva 2014/30/UE", {(2014, 30)}, True),
        ("la Directiva 2009/48/CE y 2014/35/UE", {(2009, 48)}, True),
        ("la Directiva 2009/48/CE y el Reglamento (CE) 765/2008", {(2009, 48)}, True),
        ("la Directiva 12/34/CE", set(), True),
        ("el Reglamento 765/2008, de 9 de julio", set(), False),
        ("", set(), False),
    ],
)
def test_a_designation_is_read_or_declared_ambiguous_never_guessed(text, found, ambiguous):
    designations, unreadable = designations_in(text)

    assert set(designations) == found
    assert unreadable is ambiguous


# --- Corroboración ------------------------------------------------------------


def test_the_real_analysis_of_the_toys_decree_corroborates_the_toys_directive():
    result = corroborate(toys_anchor().relations["previous"], TOYS)

    assert result.state is Corroboration.CORROBORATED
    (match,) = result.matching
    # La relación se conserva tal cual la devolvió el BOE.
    assert match["relation_code"] == 426
    assert match["relation"] == "TRANSPONE"
    assert match["id_norma"] == "DOUE-L-2009-81173"
    assert "Directiva 2009/48/CE" in match["text"]


def test_it_does_not_corroborate_another_directive():
    assert corroborate(toys_anchor().relations["previous"], LVD).state is Corroboration.UNCORROBORATED


def test_a_regulation_is_not_something_a_national_law_transposes():
    result = corroborate(toys_anchor().relations["previous"], "32023R0988")

    assert result.state is Corroboration.NOT_ASSESSABLE


def test_a_partial_transposition_is_not_a_corroboration():
    result = corroborate([relation(427, "la Directiva 2009/48/CE")], TOYS)

    assert result.state is Corroboration.PARTIAL


def test_a_partial_relation_wins_over_a_full_one_for_the_same_directive():
    both = [relation(426, "la Directiva 2009/48/CE"), relation(427, "la Directiva 2009/48/CE")]

    assert corroborate(both, TOYS).state is Corroboration.PARTIAL


@pytest.mark.parametrize(
    "text",
    [
        "cierta directiva europea sobre juguetes",
        "la Directiva 12/34/CE",
        "las Directivas 2009/48/CE y 2014/35/UE",
        "",
    ],
)
def test_an_unreadable_or_ambiguous_relation_is_not_assessable_and_never_fuzzy_matched(text):
    """Nada de similitud textual: si año y número no se leen sin ambigüedad, no se
    compara."""
    assert corroborate([relation(426, text)], TOYS).state is Corroboration.NOT_ASSESSABLE


def test_no_transposition_relation_at_all_is_uncorroborated_not_a_contradiction():
    assert corroborate([], TOYS).state is Corroboration.UNCORROBORATED
    other = [{"id_norma": "BOE-A-1990-16514", "relation_code": 210, "relation": "DEROGA", "text": "x"}]
    assert corroborate(other, TOYS).state is Corroboration.UNCORROBORATED


# --- Evaluación de la norma nacional -------------------------------------------


def test_a_verified_corroborated_and_in_force_norm_is_ok():
    result = assess_transposition(TOYS_ID, toys_anchor(), TOYS, NOW)

    assert result.state is NationalState.VERIFIED_IN_FORCE
    assert result.corroboration is Corroboration.CORROBORATED
    assert result.ok


def test_a_repealed_norm_asks_for_review():
    metadata = parse_metadata(load("metadatos_BOE-A-1992-26318_derogada.json"), "BOE-A-1992-26318")

    result = assess_transposition(
        "BOE-A-1992-26318", toys_anchor(national_id="BOE-A-1992-26318", metadata=metadata), TOYS, NOW
    )

    assert result.state is NationalState.NOT_IN_FORCE
    assert not result.ok
    assert "repealed" in result.reasons[0]


@pytest.mark.parametrize("flag", ["estatus_derogacion", "estatus_anulacion", "vigencia_agotada"])
def test_each_status_flag_the_source_sets_counts(flag):
    metadata = dict(toys_anchor().metadata, **{flag: "S"})

    assert assess_transposition(TOYS_ID, toys_anchor(metadata=metadata), TOYS, NOW).state is (
        NationalState.NOT_IN_FORCE
    )


def test_an_outdated_consolidation_asks_for_review():
    metadata = dict(toys_anchor().metadata, estado_consolidacion={"codigo": "4", "texto": "Desactualizado"})

    result = assess_transposition(TOYS_ID, toys_anchor(metadata=metadata), TOYS, NOW)

    assert result.state is NationalState.OUTDATED_CONSOLIDATION
    assert not result.ok


@pytest.mark.parametrize("missing", ["estatus_derogacion", "estatus_anulacion", "vigencia_agotada"])
def test_a_flag_the_source_did_not_give_is_unverified_not_assumed_in_force(missing):
    metadata = {k: v for k, v in toys_anchor().metadata.items() if k != missing}

    assert assess_transposition(TOYS_ID, toys_anchor(metadata=metadata), TOYS, NOW).state is (
        NationalState.UNVERIFIED
    )


def test_a_404_never_means_the_norm_does_not_exist():
    not_consolidated = toys_anchor(consolidated=False, metadata={}, relations={}, publication_state="not_checked")

    result = assess_transposition(TOYS_ID, not_consolidated, TOYS, NOW)

    assert result.state is NationalState.NOT_CONSOLIDATED
    assert not result.ok
    assert "does not exist" in result.reasons[0]
    assert "not say" in result.reasons[0]


def test_a_check_that_was_never_made_is_never_checked():
    assert assess_transposition(TOYS_ID, None, TOYS, NOW).state is NationalState.NEVER_CHECKED


def test_an_expired_recheck_is_stale_and_says_it_is_our_policy():
    stale = toys_anchor(recheck_after=NOW - datetime.timedelta(seconds=1))

    result = assess_transposition(TOYS_ID, stale, TOYS, NOW)

    assert result.state is NationalState.STALE
    assert "not a statement" in result.reasons[0]
    assert not result.ok


@pytest.mark.parametrize("code", [220, 221, 230, 231])
def test_annulment_and_suspension_relations_are_shown_and_ask_for_review(code):
    relations = copy.deepcopy(toys_anchor().relations)
    relations["next"].append(
        {"id_norma": "BOE-A-2030-1", "relation_code": code, "relation": "X", "text": "el art. 3"}
    )

    result = assess_transposition(TOYS_ID, toys_anchor(relations=relations), TOYS, NOW)

    assert result.state is NationalState.RELATION_FLAGGED
    assert [r["relation_code"] for r in result.flagged_relations] == [code]
    # No se interpreta su efecto jurídico.
    assert "not interpreted" in result.reasons[0]


def test_ordinary_amendments_do_not_flag_anything():
    """El decreto de juguetes tiene una decena de `SE MODIFICA` y sigue en orden."""
    result = assess_transposition(TOYS_ID, toys_anchor(), TOYS, NOW)

    assert result.flagged_relations == ()


def test_a_summary_that_was_read_and_does_not_list_the_norm_is_inconsistent():
    result = assess_transposition(TOYS_ID, toys_anchor(publication_state="absent_from_summary"), TOYS, NOW)

    assert result.state is NationalState.PUBLICATION_INCONSISTENT
    assert not result.ok


@pytest.mark.parametrize("state", ["check_failed", "not_checked", "confirmed"])
def test_an_auxiliary_check_that_failed_or_did_not_apply_never_degrades_the_norm(state):
    """Un fallo de red o de lectura del sumario no es una conclusión negativa."""
    assert assess_transposition(TOYS_ID, toys_anchor(publication_state=state), TOYS, NOW).ok


def test_the_entry_into_force_date_is_kept_as_source_data_and_never_compared():
    metadata = dict(toys_anchor().metadata, fecha_vigencia="29990101")

    result = assess_transposition(TOYS_ID, toys_anchor(metadata=metadata), TOYS, NOW)

    assert result.ok
    assert result.anchor.metadata["fecha_vigencia"] == "29990101"


def test_a_norm_that_is_not_corroborated_is_not_ok_even_when_in_force():
    result = assess_transposition(TOYS_ID, toys_anchor(), LVD, NOW)

    assert result.state is NationalState.VERIFIED_IN_FORCE
    assert result.corroboration is Corroboration.UNCORROBORATED
    assert not result.ok


# --- Integración con las reglas de M41: `PASS` exige más que el texto -----------


def requirement(**overrides) -> DeclaredRequirement:
    fields = {
        "id": "req-1",
        "product_scope": "toys",
        "jurisdiction": "eu",
        "celex": TOYS,
        "regulation": "Toy Safety Directive",
        "requirement": "Toys must be safe",
        "kind": RequirementKind.OBLIGATION,
        "applicability_provenance": DECLARED,
        "declared_by": "owner",
    }
    fields.update(overrides)
    return DeclaredRequirement(**fields)


def eu_anchor() -> AnchorState:
    return AnchorState(
        found=True,
        in_force=True,
        act_type=ActType.DIRECTIVE,
        verified_at=NOW - datetime.timedelta(days=1),
        recheck_after=NOW + datetime.timedelta(days=29),
        source="eur-lex-cellar",
    )


def evidence(provenance=DECLARED) -> ComplianceEvidenceItem:
    fields = {"provenance": provenance, "declared_by": "owner"}
    if provenance is VERIFIED:
        fields["source"] = "Notified Body 0123"
    return ComplianceEvidenceItem(**fields)


def assess(*, transpositions, proofs=None, req=None):
    return assess_requirement(
        req or requirement(),
        eu_anchor(),
        [evidence()] if proofs is None else proofs,
        now=NOW,
        transpositions=transpositions,
    )


def ok_transposition():
    return assess_transposition(TOYS_ID, toys_anchor(), TOYS, NOW)


def test_a_directive_passes_only_with_a_declared_verified_corroborated_norm_and_evidence():
    result = assess(transpositions=[ok_transposition()])

    assert result.status is LegalStatus.PASS
    assert result.national[0].national_id == TOYS_ID


def test_without_compliance_evidence_the_corroborated_norm_does_not_pass():
    """`PASS` no depende solo del texto consolidado: exige evidencia de cumplimiento."""
    result = assess(transpositions=[ok_transposition()], proofs=[])

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "no compliance evidence" in result.reasons[0]


def test_a_restriction_with_a_corroborated_norm_and_no_evidence_is_blocked_as_before():
    result = assess(
        transpositions=[ok_transposition()],
        proofs=[],
        req=requirement(kind=RequirementKind.RESTRICTION),
    )

    assert result.status is LegalStatus.BLOCKED


def test_a_directive_with_no_declared_transposition_asks_for_review():
    result = assess(transpositions=[])

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "no national transposition is declared and verified" in result.reasons[0]


def test_a_free_text_reference_alone_is_a_human_declaration_and_is_not_enough():
    req = requirement(transposition_reference="Real Decreto 1205/2011", transposition_provenance=DECLARED)

    result = assess(transpositions=[], req=req)

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "human declaration only" in result.reasons[0]


def test_a_declared_but_uncorroborated_transposition_asks_for_review():
    other = assess_transposition(TOYS_ID, toys_anchor(), LVD, NOW)

    result = assess(transpositions=[other], req=requirement(celex=LVD))

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "not corroborated" in result.reasons[0]
    assert "uncorroborated" in result.reasons[0]


def test_a_partial_transposition_asks_for_review():
    anchor = toys_anchor(relations={"previous": [relation(427, "la Directiva 2009/48/CE")], "next": []})

    result = assess(transpositions=[assess_transposition(TOYS_ID, anchor, TOYS, NOW)])

    assert result.status is LegalStatus.REVIEW_REQUIRED
    assert "partial" in result.reasons[0]


def test_one_bad_norm_among_several_holds_the_requirement_back():
    bad = assess_transposition(TOYS_ID, None, TOYS, NOW)

    result = assess(transpositions=[ok_transposition(), bad])

    assert result.status is LegalStatus.REVIEW_REQUIRED


def test_informational_boe_data_caps_confidence_at_seven_tenths():
    """Regla interna, no calibrada: entre EUR-Lex (0,8) y lo declarado (0,6)."""
    req = requirement(applicability_provenance=VERIFIED, applicability_source="Legal counsel")

    result = assess(transpositions=[ok_transposition()], proofs=[evidence(VERIFIED)], req=req)

    assert result.status is LegalStatus.PASS
    assert result.confidence == INFORMATIONAL_CONFIDENCE_CEILING == 0.7


def test_a_regulation_is_untouched_by_all_this():
    req = requirement(celex="32023R0988")
    regulation = AnchorState(
        found=True,
        in_force=True,
        act_type=ActType.REGULATION,
        verified_at=NOW,
        recheck_after=NOW + datetime.timedelta(days=30),
        source="eur-lex-cellar",
    )

    result = assess_requirement(req, regulation, [evidence()], now=NOW)

    assert result.status is LegalStatus.PASS
    assert result.national == ()
