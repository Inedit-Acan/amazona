"""Declarar, comprobar y evaluar requisitos regulatorios (Milestone 41, ADR 0019),
con la fuente sustituida por una falsa: ninguna prueba toca la red."""

import datetime

import pytest
from regulatory_test_support import GPSR, LVD, NOW, FakeSource, anchor
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.costs.service import ApiBudgetExceededError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.regulatory_anchor import RegulatoryAnchor
from app.integrations.ports import ProviderKind
from app.integrations.regulatory.eur_lex import AnchorUnavailableError
from app.legal.regulatory import RegulatoryService, SourceNotConfiguredError
from app.legal.service import LegalComplianceService
from app.sourcing.provenance import MissingVerifierError


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_product(db: Session, category: str = "Toys") -> Product:
    product = Product(name="Wooden train", category=category, created_by="owner@amazona.local")
    db.add(product)
    db.commit()
    return product


def service(db, source=None, days=30, now=NOW) -> RegulatoryService:
    return RegulatoryService(
        db, source=source, settings=Settings(legal_anchor_recheck_days=days), now=now
    )


def declare(svc: RegulatoryService, **overrides):
    fields = {
        "actor": "owner@amazona.local",
        "product_scope": "Toys",
        "jurisdiction": "eu",
        "celex": GPSR,
        "regulation": "General Product Safety Regulation",
        "requirement": "A documented safety assessment must exist",
        "kind": "obligation",
    }
    fields.update(overrides)
    return svc.declare(**fields)


# --- Declarar: lo hace una persona, y se rechaza lo que no es un hecho legal ----


def test_a_declared_requirement_keeps_who_said_it_and_with_what_provenance(db):
    row = declare(service(db))

    assert row.declared_by == "owner@amazona.local"
    assert row.applicability_provenance == "declared"
    assert row.kind == "obligation"


def test_declaring_leaves_an_audit_row(db):
    declare(service(db))

    entry = db.query(AuditLog).filter_by(action="regulatory_requirement.declare").one()
    assert entry.actor == "owner@amazona.local"


@pytest.mark.parametrize("jurisdiction", ["es", "us", "mx", ""])
def test_only_the_jurisdiction_the_source_covers_can_be_declared(db, jurisdiction):
    with pytest.raises(ValidationError):
        declare(service(db), jurisdiction=jurisdiction)


def test_a_malformed_celex_cannot_be_declared(db):
    with pytest.raises(ValidationError):
        declare(service(db), celex="not-a-celex")


def test_third_party_applicability_without_an_issuer_cannot_be_declared(db):
    with pytest.raises(MissingVerifierError):
        declare(service(db), applicability_provenance="third_party_verified")


def test_a_simulated_or_unknown_applicability_cannot_be_declared(db):
    for provenance in ("simulated", "unknown", "amazona_estimate"):
        with pytest.raises(ValidationError):
            declare(service(db), applicability_provenance=provenance)


def test_a_requirement_without_its_text_cannot_be_declared(db):
    with pytest.raises(ValidationError):
        declare(service(db), requirement="   ")


def test_scope_matching_is_deterministic_and_not_by_similarity(db):
    svc = service(db)
    declare(svc, product_scope="Juguetes Ñoños")

    assert svc.active_for(scope="  juguetes   ñoños ", jurisdiction="EU")  # mismo alcance
    assert not svc.active_for(scope="Juguete", jurisdiction="eu")  # parecido, no igual
    assert not svc.active_for(scope="Juguetes", jurisdiction="eu")


# --- Modificar es sustituir; retirar conserva la fila --------------------------


def test_superseding_marks_the_old_row_and_creates_a_new_one(db):
    svc = service(db)
    old = declare(svc)

    new = svc.supersede(
        old.id,
        actor="admin@amazona.local",
        product_scope="Toys",
        jurisdiction="eu",
        celex=GPSR,
        regulation="GPSR",
        requirement="Updated text",
        kind="restriction",
    )

    assert old.superseded_by_id == new.id
    assert [r.id for r in svc.list_active()] == [new.id]


def test_a_superseded_or_withdrawn_requirement_cannot_be_changed_again(db):
    svc = service(db)
    row = declare(svc)
    svc.withdraw(row.id, actor="owner")

    with pytest.raises(ValidationError):
        svc.withdraw(row.id, actor="owner")
    assert row.withdrawn_at is not None
    assert svc.list_active() == []


def test_a_requirement_that_does_not_exist_cannot_be_withdrawn(db):
    with pytest.raises(NotFoundError):
        service(db).withdraw("nope", actor="owner")


# --- Evidencia -----------------------------------------------------------------


def test_evidence_third_party_needs_its_issuer(db):
    svc = service(db)
    product = make_product(db)
    row = declare(svc)

    with pytest.raises(MissingVerifierError):
        svc.add_evidence(
            actor="owner", product_id=product.id, requirement_id=row.id,
            provenance="third_party_verified",
        )


def test_evidence_for_a_product_that_does_not_exist_is_refused(db):
    svc = service(db)
    row = declare(svc)

    with pytest.raises(NotFoundError):
        svc.add_evidence(actor="owner", product_id="nope", requirement_id=row.id)


# --- Comprobar contra la fuente ------------------------------------------------


def test_verify_stores_what_the_source_said_with_our_recheck_policy(db):
    source = FakeSource({GPSR: anchor(GPSR)})
    svc = service(db, source, days=30)

    row = svc.verify(GPSR)

    assert row.found is True
    assert row.in_force is True
    assert row.provenance == "third_party_verified"
    assert row.provider == "eur-lex-cellar"
    assert row.act_type == "regulation"
    assert row.source_effective_from == ["2024-12-13"]
    # Se guarda tal cual lo entrega la fuente, sin interpretar.
    assert row.source_effective_to == "9999-12-31"
    assert row.evidence == {"resource_legal_in-force": ["1"]}
    assert (row.recheck_after - row.verified_at).days == 30


def test_the_recheck_window_is_configurable(db):
    row = service(db, FakeSource({GPSR: anchor(GPSR)}), days=7).verify(GPSR)

    assert (row.recheck_after - row.verified_at).days == 7


def test_a_not_found_answer_is_stored_as_the_source_speaking_not_as_a_failure(db):
    row = service(db, FakeSource()).verify("32099R9999")

    assert row.found is False
    assert row.in_force is None


def test_an_unclassified_act_type_is_other_never_assumed_applicable(db):
    row = service(db, FakeSource({GPSR: anchor(GPSR, code="DEC_IMPL")})).verify(GPSR)

    assert row.act_type == "other"
    assert row.act_type_code == "DEC_IMPL"


def test_a_source_failure_stores_nothing(db):
    source = FakeSource({GPSR: AnchorUnavailableError("down")})

    with pytest.raises(AnchorUnavailableError):
        service(db, source).verify(GPSR)

    assert db.query(RegulatoryAnchor).count() == 0


def test_without_a_real_source_configured_nothing_is_anchored(db):
    svc = RegulatoryService(db, settings=Settings(regulatory_provider=ProviderKind.MOCK), now=NOW)

    with pytest.raises(SourceNotConfiguredError):
        svc.verify(GPSR)


def test_a_fresh_anchor_is_not_asked_again(db):
    source = FakeSource({GPSR: anchor(GPSR)})
    svc = service(db, source)
    svc.verify(GPSR)

    current, failure = svc.ensure_fresh(GPSR, correlation_id="c-1")

    assert failure is None
    assert current is not None
    assert source.asked == [GPSR]


def test_a_stale_anchor_is_asked_again(db):
    source = FakeSource({GPSR: anchor(GPSR, when=NOW - datetime.timedelta(days=40))})
    service(db, source).verify(GPSR)

    current, failure = service(db, source).ensure_fresh(GPSR, correlation_id="c-1")

    assert failure is None
    assert source.asked == [GPSR, GPSR]
    assert db.query(RegulatoryAnchor).count() == 2  # una comprobación nueva es una fila nueva


@pytest.mark.parametrize(
    "error", [AnchorUnavailableError("down"), ApiBudgetExceededError("no budget")]
)
def test_when_it_cannot_ask_the_old_anchor_is_kept_and_the_reason_returned(db, error):
    old = FakeSource({GPSR: anchor(GPSR, when=NOW - datetime.timedelta(days=40))})
    service(db, old).verify(GPSR)

    current, failure = service(db, FakeSource({GPSR: error})).ensure_fresh(
        GPSR, correlation_id="c-1"
    )

    assert current is not None and failure
    assert db.query(RegulatoryAnchor).count() == 1


# --- El análisis real de Legal --------------------------------------------------


@pytest.fixture()
def real_mode(monkeypatch):
    monkeypatch.setattr(
        "app.legal.service.get_settings",
        lambda: Settings(regulatory_provider=ProviderKind.REAL),
    )


def run_legal(db, product, svc, market="eu"):
    return LegalComplianceService(db, regulatory=svc).run_analysis(
        product_id=product.id, market=market, correlation_id="corr-1"
    )


def test_with_nothing_declared_the_analysis_is_unknown_and_reviewed_not_blocked(db, real_mode):
    product = make_product(db)

    analysis = run_legal(db, product, service(db, FakeSource()))

    assert analysis.data["legal_status"] == "UNKNOWN"
    assert analysis.recommendation == "REVIEW"
    assert analysis.restricted is None


def test_a_verified_requirement_with_evidence_passes_and_still_disclaims(db, real_mode):
    svc = service(db, FakeSource({GPSR: anchor(GPSR)}))
    product = make_product(db)
    row = declare(svc)
    svc.add_evidence(actor="owner", product_id=product.id, requirement_id=row.id)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "PASS"
    assert analysis.recommendation == "GO"
    assert "does not replace professional legal review" in analysis.data["disclaimer"]
    assert "not a statement that the product is legal" in analysis.data["reasons"][0]


def test_the_three_questions_come_out_separately_per_requirement(db, real_mode):
    svc = service(db, FakeSource({GPSR: anchor(GPSR)}))
    product = make_product(db)
    declare(svc)

    analysis = run_legal(db, product, svc)

    (req,) = analysis.data["requirements"]
    assert req["applicability"]["provenance"] == "declared"
    assert req["existence"]["state"] == "verified_in_force"
    assert req["existence"]["source_effective_to"] == "9999-12-31"
    assert req["compliance"]["state"] == "none"
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"


def test_a_restriction_without_evidence_blocks_and_marks_the_product_restricted(db, real_mode):
    svc = service(db, FakeSource({GPSR: anchor(GPSR)}))
    product = make_product(db)
    declare(svc, kind="restriction")

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "BLOCKED"
    assert analysis.recommendation == "NO_GO"
    assert analysis.restricted is True


def test_if_the_source_is_down_legal_asks_for_review_and_never_concludes(db, real_mode):
    svc = service(db, FakeSource({GPSR: AnchorUnavailableError("down")}))
    product = make_product(db)
    declare(svc, kind="restriction")

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert analysis.recommendation == "REVIEW"
    assert GPSR in analysis.data["source_errors"]


def test_a_directive_without_transposition_never_passes(db, real_mode):
    svc = service(db, FakeSource({LVD: anchor(LVD, code="DIR")}))
    product = make_product(db)
    row = declare(svc, celex=LVD, regulation="Low Voltage Directive")
    svc.add_evidence(actor="owner", product_id=product.id, requirement_id=row.id)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"


def test_another_jurisdiction_is_unknown_even_if_eu_requirements_exist(db, real_mode):
    svc = service(db, FakeSource({GPSR: anchor(GPSR)}))
    product = make_product(db)
    declare(svc)

    analysis = run_legal(db, product, svc, market="us")

    assert analysis.data["legal_status"] == "UNKNOWN"


def test_the_legacy_certification_flag_is_reported_as_ignored_not_silently_dropped(db, real_mode):
    product = make_product(db)

    analysis = LegalComplianceService(db, regulatory=service(db, FakeSource())).run_analysis(
        product_id=product.id, market="eu", correlation_id="c", certification_available=True
    )

    assert analysis.data["certification_flag_ignored"] is True


def test_the_real_output_does_not_invent_certifications_or_terms(db, real_mode):
    """Ausente se queda ausente: sin `required_certifications` ni un texto de
    términos que nadie ha escrito."""
    product = make_product(db)

    analysis = run_legal(db, product, service(db, FakeSource()))

    assert "required_certifications" not in analysis.data
    assert "terms_and_conditions" not in analysis.data


def test_the_real_analysis_is_audited(db, real_mode):
    product = make_product(db)

    run_legal(db, product, service(db, FakeSource()))

    assert db.query(AuditLog).filter_by(action="legal.run").count() == 1


def test_with_the_mock_configured_the_analysis_is_exactly_the_old_one(db, monkeypatch):
    monkeypatch.setattr(
        "app.legal.service.get_settings", lambda: Settings(regulatory_provider=ProviderKind.MOCK)
    )
    product = make_product(db, category="accessories")

    analysis = LegalComplianceService(db).run_analysis(
        product_id=product.id, market="eu", correlation_id="c"
    )

    assert "legal_status" not in analysis.data
    assert "required_certifications" in analysis.data
    assert "terms_and_conditions" in analysis.data


def test_once_the_source_fails_the_rest_of_the_analysis_does_not_keep_asking(db, real_mode):
    """Un trabajo tiene un arriendo de 60 s: varios timeouts seguidos lo agotarían."""
    source = FakeSource({GPSR: AnchorUnavailableError("timed out"), LVD: anchor(LVD)})
    svc = service(db, source)
    product = make_product(db)
    declare(svc)
    declare(svc, celex=LVD, regulation="Low Voltage Directive")

    analysis = run_legal(db, product, svc)

    assert source.asked == [GPSR]  # la segunda norma no se pregunta
    assert set(analysis.data["source_errors"]) == {GPSR, LVD}
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
