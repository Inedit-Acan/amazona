"""Declarar, verificar y evaluar transposiciones nacionales (Milestone 43, ADR 0021),
con la fuente del BOE sustituida por una falsa: ninguna prueba toca la red.

Lo que se protege: la norma la **declara una persona** y el BOE solo la verifica; todo
o nada al guardar; y `PASS` exige transposición estructurada verificada y corroborada
**más** evidencia de cumplimiento.
"""

import datetime

import pytest
from national_test_support import TOYS, TOYS_ID, FakeNationalSource, toys_record
from regulatory_test_support import GPSR, LVD, NOW, FakeSource, anchor
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.costs.service import ApiBudgetExceededError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.national_anchor import NationalAnchor
from app.db.models.product import Product
from app.integrations.ports import ProviderKind
from app.integrations.regulatory.boe import NationalSourceUnavailableError
from app.legal.national import ATTRIBUTION, NOTICE
from app.legal.regulatory import RegulatoryService, SourceNotConfiguredError
from app.legal.service import LegalComplianceService

ACTOR = "owner@amazona.local"


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
    product = Product(name="Wooden train", category=category, created_by=ACTOR)
    db.add(product)
    db.commit()
    return product


def service(db, *, eu=None, national=None, days=30, now=NOW, provider=ProviderKind.REAL):
    return RegulatoryService(
        db,
        source=eu,
        national_source=national,
        settings=Settings(_env_file=None, legal_anchor_recheck_days=days, national_law_provider=provider),
        now=now,
    )


def declare_toys(svc, **overrides):
    fields = {
        "actor": ACTOR,
        "product_scope": "Toys",
        "jurisdiction": "eu",
        "celex": TOYS,
        "regulation": "Toy Safety Directive",
        "requirement": "Toys must be safe",
        "kind": "obligation",
    }
    fields.update(overrides)
    return svc.declare(**fields)


# --- Declarar: lo hace una persona, y no se propone nada -------------------------


def test_a_person_declares_the_national_norm_and_it_stays_declared(db):
    svc = service(db)
    requirement = declare_toys(svc)

    row = svc.declare_transposition(
        actor=ACTOR, requirement_id=requirement.id, national_id="boe-a-2011-14252", note="RD juguetes"
    )

    assert row.national_id == TOYS_ID
    assert row.provenance == "declared"
    assert row.declared_by == ACTOR
    assert row.requirement_id == requirement.id
    assert db.query(AuditLog).filter_by(action="national_transposition.declare").one().actor == ACTOR


def test_only_a_directive_can_have_a_national_transposition(db):
    svc = service(db)
    regulation = declare_toys(svc, celex=GPSR, regulation="GPSR")

    with pytest.raises(ValidationError, match="not a directive"):
        svc.declare_transposition(actor=ACTOR, requirement_id=regulation.id, national_id=TOYS_ID)


@pytest.mark.parametrize("bad", ["", "Real Decreto 1205/2011", "DOUE-L-2009-81173", "BOE-A-11-1"])
def test_an_identifier_that_is_not_a_boe_id_is_refused_and_nothing_is_proposed(db, bad):
    svc = service(db)
    requirement = declare_toys(svc)

    with pytest.raises(ValidationError):
        svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=bad)


def test_the_same_norm_cannot_be_declared_twice_for_a_requirement(db):
    svc = service(db)
    requirement = declare_toys(svc)
    svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)

    with pytest.raises(ValidationError, match="already declared"):
        svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)


def test_a_transposition_needs_an_active_requirement(db):
    svc = service(db)
    requirement = declare_toys(svc)
    svc.withdraw(requirement.id, actor=ACTOR)

    with pytest.raises(ValidationError, match="no longer active"):
        svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)
    with pytest.raises(NotFoundError):
        svc.declare_transposition(actor=ACTOR, requirement_id="missing", national_id=TOYS_ID)


def test_withdrawing_keeps_the_row_and_audits(db):
    svc = service(db)
    requirement = declare_toys(svc)
    row = svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)

    svc.withdraw_transposition(row.id, actor=ACTOR)

    assert svc.active_transpositions(requirement.id) == []
    assert svc.get_transposition(row.id).withdrawn_at is not None
    assert db.query(AuditLog).filter_by(action="national_transposition.withdraw").count() == 1
    with pytest.raises(ValidationError, match="already withdrawn"):
        svc.withdraw_transposition(row.id, actor=ACTOR)


def test_the_free_text_of_milestone_41_is_kept_untouched(db):
    svc = service(db)

    row = declare_toys(
        svc, transposition_reference="Real Decreto 1205/2011", transposition_provenance="declared"
    )

    assert row.transposition_reference == "Real Decreto 1205/2011"
    assert row.transposition_provenance == "declared"


# --- Verificar: la fuente ancla, y todo o nada -------------------------------------


def test_a_verification_stores_the_source_data_verbatim_with_the_required_notice(db):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)

    row = svc.verify_national(TOYS_ID, correlation_id="c-1")

    assert national.asked == [TOYS_ID]
    assert row.provenance == "third_party_verified"
    assert row.consolidated is True
    assert row.informational is True
    assert row.notice == NOTICE
    assert row.attribution == ATTRIBUTION
    assert row.source_metadata["fecha_publicacion"] == "20110831"
    assert row.source_metadata["estatus_derogacion"] == "N"
    assert row.source_updated_at == row.source_metadata["fecha_actualizacion"]
    assert row.relations["previous"][1]["relation_code"] == 426
    assert row.publication_state == "confirmed"
    assert row.publication_url == "https://www.boe.es/buscar/doc.php?id=BOE-A-2011-14252"
    # Política nuestra, no un plazo jurídico.
    assert row.recheck_after - row.verified_at == datetime.timedelta(days=30)
    entry = db.query(AuditLog).filter_by(action="national_anchor.verify").one()
    assert entry.actor == "system:boe-open-data"
    assert entry.after["consolidated"] is True


def test_the_text_of_the_norm_is_never_stored(db):
    svc = service(db, national=FakeNationalSource({TOYS_ID: toys_record(when=NOW)}))

    row = svc.verify_national(TOYS_ID)

    columns = {c.name for c in NationalAnchor.__table__.columns}
    assert not {"text", "texto", "body", "content"} & columns
    assert "texto" not in row.source_metadata


def test_a_second_verification_is_a_new_row_and_the_first_is_kept(db):
    later = NOW + datetime.timedelta(days=1)
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)
    svc.verify_national(TOYS_ID)
    national.answers[TOYS_ID] = toys_record(when=later)

    svc.verify_national(TOYS_ID)

    assert db.query(NationalAnchor).count() == 2
    assert svc.latest_national_anchor(TOYS_ID).verified_at.replace(tzinfo=datetime.UTC) == later


@pytest.mark.parametrize(
    "failure",
    [
        NationalSourceUnavailableError("the BOE did not answer"),
        NationalSourceUnavailableError("the BOE metadata answer is not valid JSON"),
        NationalSourceUnavailableError("the BOE answered HTTP 500"),
        ApiBudgetExceededError("no room"),
    ],
)
def test_a_failed_verification_stores_nothing(db, failure):
    svc = service(db, national=FakeNationalSource({TOYS_ID: failure}))

    with pytest.raises(type(failure)):
        svc.verify_national(TOYS_ID)

    assert db.query(NationalAnchor).count() == 0
    assert db.query(AuditLog).filter_by(action="national_anchor.verify").count() == 0


def test_a_404_is_stored_as_not_consolidated_and_not_as_nonexistent(db):
    svc = service(db, national=FakeNationalSource({TOYS_ID: toys_record(when=NOW, consolidated=False)}))

    row = svc.verify_national(TOYS_ID)

    assert row.consolidated is False
    assert row.source_metadata is None and row.relations is None
    assert row.notice == NOTICE


def test_a_failed_publication_check_is_stored_as_check_failed_never_as_absent(db):
    svc = service(
        db, national=FakeNationalSource({TOYS_ID: toys_record(when=NOW, publication="check_failed")})
    )

    row = svc.verify_national(TOYS_ID)

    assert row.publication_state == "check_failed"


def test_without_a_real_source_configured_nothing_is_asked(db):
    svc = service(db, provider=ProviderKind.MOCK)

    with pytest.raises(SourceNotConfiguredError, match="NATIONAL_LAW_PROVIDER"):
        svc.verify_national(TOYS_ID)

    assert db.query(NationalAnchor).count() == 0


def test_without_the_right_to_store_nothing_is_asked(db, monkeypatch):
    monkeypatch.setattr("app.legal.regulatory.permits", lambda provider, right: False)
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)

    with pytest.raises(SourceNotConfiguredError, match="rights"):
        svc.verify_national(TOYS_ID)

    assert national.asked == []


def test_an_invalid_identifier_is_never_asked(db):
    national = FakeNationalSource()
    svc = service(db, national=national)

    with pytest.raises(ValidationError):
        svc.verify_national("not-an-id")

    assert national.asked == []


# --- Recomprobar según nuestra política -----------------------------------------


def test_a_fresh_check_is_not_asked_again(db):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)
    svc.verify_national(TOYS_ID)

    current, failure = svc.ensure_fresh_national(TOYS_ID, correlation_id="c")

    assert failure is None and current is not None
    assert national.asked == [TOYS_ID]


def test_an_expired_check_is_repeated(db):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)
    svc.verify_national(TOYS_ID)
    later = service(db, national=national, now=NOW + datetime.timedelta(days=31))
    national.answers[TOYS_ID] = toys_record(when=NOW + datetime.timedelta(days=31))

    later.ensure_fresh_national(TOYS_ID, correlation_id="c")

    assert national.asked == [TOYS_ID, TOYS_ID]
    assert db.query(NationalAnchor).count() == 2


def test_if_the_recheck_fails_the_old_check_is_kept_and_the_reason_returned(db):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, national=national)
    svc.verify_national(TOYS_ID)
    later = service(db, national=national, now=NOW + datetime.timedelta(days=31))
    national.answers[TOYS_ID] = NationalSourceUnavailableError("timed out")

    current, failure = later.ensure_fresh_national(TOYS_ID, correlation_id="c")

    assert current is not None and "timed out" in failure
    assert db.query(NationalAnchor).count() == 1


# --- El análisis real de Legal ---------------------------------------------------


@pytest.fixture()
def real_mode(monkeypatch):
    monkeypatch.setattr(
        "app.legal.service.get_settings", lambda: Settings(_env_file=None, regulatory_provider=ProviderKind.REAL)
    )


def run_legal(db, product, svc):
    return LegalComplianceService(db, regulatory=svc).run_analysis(
        product_id=product.id, market="eu", correlation_id="corr-1"
    )


def toys_setup(db, *, national=None, evidence=True, transposition=True, provider=ProviderKind.REAL):
    eu = FakeSource({TOYS: anchor(TOYS, code="DIR")})
    svc = service(db, eu=eu, national=national, provider=provider)
    product = make_product(db)
    requirement = declare_toys(svc)
    if transposition:
        svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)
    if evidence:
        svc.add_evidence(
            actor=ACTOR, product_id=product.id, requirement_id=requirement.id, provenance="declared"
        )
    return svc, product, requirement


def test_a_directive_passes_with_a_verified_corroborated_norm_and_compliance_evidence(db, real_mode):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc, product, _ = toys_setup(db, national=national)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "PASS"
    assert analysis.recommendation == "GO"
    item = analysis.data["requirements"][0]["national"][0]
    assert item["state"] == "verified_in_force" and item["ok"] is True
    assert item["eu_relation"]["corroboration"] == "corroborated"
    assert item["eu_relation"]["matching_relations"][0]["relation"] == "TRANSPONE"
    assert item["declared"]["provenance"] == "declared"
    assert item["publication"]["state"] == "confirmed"
    assert item["publication"]["official_url"].endswith("BOE-A-2011-14252")
    # Informativo: viaja en el resultado, con la atribución.
    assert item["informational"] is True
    assert item["notice"] == NOTICE and item["attribution"] == ATTRIBUTION
    # Fechas como las dio la fuente, sin interpretar.
    assert item["source_status"]["fecha_vigencia"] == "20110901"
    assert item["source_status"]["estatus_derogacion"] == "N"


def test_the_result_confidence_is_capped_by_the_informational_source(db, real_mode):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc, product, _ = toys_setup(db, national=national)

    analysis = run_legal(db, product, svc)

    assert analysis.confidence <= 0.7


def test_without_compliance_evidence_a_corroborated_norm_still_does_not_pass(db, real_mode):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc, product, _ = toys_setup(db, national=national, evidence=False)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert analysis.recommendation == "REVIEW"
    assert "no compliance evidence" in " ".join(analysis.data["reasons"])


def test_a_directive_with_no_declared_transposition_is_reviewed(db, real_mode):
    svc, product, _ = toys_setup(db, national=FakeNationalSource(), transposition=False)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert "no national transposition is declared and verified" in " ".join(analysis.data["reasons"])


def test_only_a_free_text_transposition_is_not_enough(db, real_mode):
    eu = FakeSource({TOYS: anchor(TOYS, code="DIR")})
    svc = service(db, eu=eu, national=FakeNationalSource())
    product = make_product(db)
    requirement = declare_toys(
        svc, transposition_reference="Real Decreto 1205/2011", transposition_provenance="declared"
    )
    svc.add_evidence(actor=ACTOR, product_id=product.id, requirement_id=requirement.id)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert "human declaration only" in " ".join(analysis.data["reasons"])
    # Se conserva y se muestra como declaración humana.
    assert analysis.data["requirements"][0]["transposition"]["reference"] == "Real Decreto 1205/2011"


def test_a_declared_norm_the_source_does_not_corroborate_is_reviewed(db, real_mode):
    """El BOE dice `TRANSPONE` de la 2009/48; el requisito declara la 2014/35."""
    eu = FakeSource({LVD: anchor(LVD, code="DIR")})
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc = service(db, eu=eu, national=national)
    product = make_product(db)
    requirement = declare_toys(svc, celex=LVD, regulation="Low Voltage Directive")
    svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=TOYS_ID)
    svc.add_evidence(actor=ACTOR, product_id=product.id, requirement_id=requirement.id)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert "not corroborated" in " ".join(analysis.data["reasons"])


def test_a_norm_flagged_as_repealed_is_reviewed_and_never_blocked(db, real_mode):
    national = FakeNationalSource(
        {TOYS_ID: toys_record(when=NOW, metadata={"estatus_derogacion": "S", "fecha_derogacion": "20300101"})}
    )
    svc, product, _ = toys_setup(db, national=national)

    analysis = run_legal(db, product, svc)

    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert analysis.recommendation == "REVIEW"
    assert analysis.restricted is None


def test_a_404_norm_is_reviewed_with_the_reason_kept(db, real_mode):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW, consolidated=False)})
    svc, product, _ = toys_setup(db, national=national)

    analysis = run_legal(db, product, svc)

    item = analysis.data["requirements"][0]["national"][0]
    assert item["state"] == "not_consolidated"
    assert "does not say the norm does not exist" in " ".join(item["reasons"])
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"


def test_an_expired_recheck_is_reviewed_as_stale(db, real_mode):
    national = FakeNationalSource({TOYS_ID: toys_record(when=NOW)})
    svc, product, _ = toys_setup(db, national=national)
    svc.verify_national(TOYS_ID)
    later = service(
        db,
        eu=FakeSource({TOYS: anchor(TOYS, code="DIR", when=NOW + datetime.timedelta(days=40))}),
        national=FakeNationalSource({TOYS_ID: NationalSourceUnavailableError("down")}),
        now=NOW + datetime.timedelta(days=40),
    )

    analysis = run_legal(db, product, later)

    item = analysis.data["requirements"][0]["national"][0]
    assert item["state"] == "stale"
    assert TOYS_ID in analysis.data["source_errors"]
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"


def test_when_the_boe_fails_once_the_rest_of_the_analysis_does_not_keep_asking(db, real_mode):
    """Un trabajo tiene un arriendo de 60 s (ADR 0009)."""
    other = "BOE-A-2015-10566"
    national = FakeNationalSource(
        {TOYS_ID: NationalSourceUnavailableError("timed out"), other: toys_record(when=NOW)}
    )
    svc, product, requirement = toys_setup(db, national=national)
    svc.declare_transposition(actor=ACTOR, requirement_id=requirement.id, national_id=other)

    analysis = run_legal(db, product, svc)

    assert national.asked == [TOYS_ID]
    assert set(analysis.data["source_errors"]) == {TOYS_ID, other}
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"


def test_with_the_national_provider_on_mock_the_norm_is_never_asked_and_stays_unchecked(db, real_mode):
    svc, product, _ = toys_setup(db, national=None, provider=ProviderKind.MOCK)

    analysis = run_legal(db, product, svc)

    item = analysis.data["requirements"][0]["national"][0]
    assert item["state"] == "never_checked"
    assert "NATIONAL_LAW_PROVIDER" in analysis.data["source_errors"][TOYS_ID]
    assert analysis.data["legal_status"] == "REVIEW_REQUIRED"
    assert db.query(NationalAnchor).count() == 0


def test_with_the_regulatory_mock_configured_the_analysis_is_exactly_the_old_one(db, monkeypatch):
    monkeypatch.setattr(
        "app.legal.service.get_settings",
        lambda: Settings(_env_file=None, regulatory_provider=ProviderKind.MOCK),
    )
    product = make_product(db, category="accessories")

    analysis = LegalComplianceService(db).run_analysis(
        product_id=product.id, market="eu", correlation_id="c"
    )

    assert "legal_status" not in analysis.data
    assert "required_certifications" in analysis.data
    assert "national" not in str(analysis.data)
