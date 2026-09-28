"""La entrada manual de proveedores reales (Milestone 39, ADR 0017).

Es la razón de ser del milestone: un precio de proveedor negociado no lo publica
ninguna API, lo trae una persona de una conversación. Este camino de escritura
se sostiene **permanentemente**, no como arranque hasta que haya directorio.
"""

import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError, ValidationError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.sourcing.capabilities import SupplyCapability, profile, resolve, unanswered
from app.sourcing.provenance import MissingVerifierError, SupplierFactProvenance
from app.sourcing.risk import RiskDimension, RiskLevel
from app.sourcing.service import SourcingService, supplier_identity_verified


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def product(db_session: Session) -> Product:
    product = Product(
        name="Wireless earbuds", category="electronics", created_by="owner@amazona.local"
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture()
def service(db_session: Session) -> SourcingService:
    return SourcingService(db_session)


def record(service: SourcingService, **kwargs) -> Supplier:
    kwargs.setdefault("name", "Fábrica Real S.L.")
    kwargs.setdefault("country", "ES")
    return service.record_supplier(actor="owner@amazona.local", correlation_id="corr-1", **kwargs)


# --- Alta de proveedor -------------------------------------------------------


def test_a_manually_entered_supplier_is_stored_with_its_identity(service, db_session):
    supplier = record(service, city="Valencia", website="https://fabrica.example")

    assert supplier.identity_key
    assert supplier.identity_method == "normalised"
    assert supplier.verification == SupplierFactProvenance.SUPPLIER_CLAIM
    assert supplier.last_checked_at is not None


def test_entering_the_same_company_twice_does_not_create_two(service, db_session):
    """El nombre lo teclea una persona: sin identidad, un espacio de más creaba
    una empresa nueva."""
    first = record(service, name="Fábrica Real S.L.")
    second = record(service, name="  fábrica   REAL  s.l. ")

    assert second.id == first.id
    assert db_session.query(Supplier).count() == 1


def test_the_same_name_in_two_countries_stays_two_companies(service, db_session):
    record(service, name="Acme", country="ES")
    record(service, name="Acme", country="CN")

    assert db_session.query(Supplier).count() == 2


def test_a_partial_update_does_not_erase_what_was_already_known(service):
    """Sobrescribir con nulos convertiría cada corrección parcial en una
    pérdida de datos silenciosa."""
    record(service, city="Valencia", website="https://fabrica.example")

    updated = record(service, city="Paterna")

    assert updated.city == "Paterna"
    assert updated.website == "https://fabrica.example"


def test_third_party_verification_without_an_issuer_is_refused(service):
    with pytest.raises(MissingVerifierError, match="name the verifier"):
        record(service, verification="third_party_verified")


def test_a_supplier_nobody_rated_has_no_reliability_not_a_zero(service):
    supplier = record(service)

    assert supplier.reliability_score is None
    assert supplier.reliability_provenance is None


def test_recording_a_supplier_is_audited(service, db_session):
    supplier = record(service)

    entry = db_session.query(AuditLog).filter_by(action="supplier.record").one()
    assert entry.resource == f"supplier:{supplier.id}"
    assert entry.actor == "owner@amazona.local"


# --- Alta de cotización ------------------------------------------------------


def quote(service: SourcingService, supplier: Supplier, product: Product, **kwargs):
    return service.record_quote(
        supplier_id=supplier.id,
        product_id=product.id,
        actor="owner@amazona.local",
        correlation_id="corr-2",
        **kwargs,
    )


def test_a_real_quote_keeps_every_commercial_term(service, product):
    supplier = record(service)

    stored = quote(
        service,
        supplier,
        product,
        unit_price=6.4,
        currency="EUR",
        quoted_unit="piece",
        quoted_quantity=1,
        moq=25,
        lead_time_days=7,
        transit_days=3,
        transport_mode="road",
        incoterm="DDP",
        payment_terms="50 % anticipo, 50 % a 30 días",
        destination_market="eu",
        logistics_cost_per_unit=0.42,
        valid_until=datetime.datetime(2026, 12, 31, tzinfo=datetime.UTC),
    )

    assert stored.currency == "EUR"
    assert stored.incoterm == "DDP"
    assert stored.payment_terms.startswith("50 %")
    assert stored.destination_market == "eu"
    assert stored.total_landed_cost_per_unit == 6.82
    assert stored.provenance == SupplierFactProvenance.SUPPLIER_CLAIM
    assert stored.source == "manual:owner@amazona.local"


def test_what_the_supplier_did_not_say_stays_unsaid(service, product):
    """Sin MOQ no hay MOQ de uno, y sin logística no hay coste de aterrizaje
    aunque haya precio: sumar cero diría que el transporte es gratis."""
    supplier = record(service)

    stored = quote(service, supplier, product, unit_price=6.4, currency="EUR")

    assert stored.moq is None
    assert stored.lead_time_days is None
    assert stored.logistics_cost_per_unit is None
    assert stored.total_landed_cost_per_unit is None


def test_a_price_without_a_currency_is_refused(service, product):
    supplier = record(service)

    with pytest.raises(ValidationError, match="exchange rate of 1.00"):
        quote(service, supplier, product, unit_price=6.4)


def test_an_incoterm_that_does_not_exist_is_refused(service, product):
    supplier = record(service)

    with pytest.raises(ValidationError, match="Incoterms 2020"):
        quote(service, supplier, product, incoterm="DPP")


def test_a_currency_outside_the_catalogue_is_refused(service, product):
    supplier = record(service)

    with pytest.raises(ValidationError, match="known trade currency"):
        quote(service, supplier, product, unit_price=1.0, currency="XYZ")


def test_an_offer_cannot_expire_before_it_starts(service, product):
    supplier = record(service)

    with pytest.raises(ValidationError, match="expire before it starts"):
        quote(
            service,
            supplier,
            product,
            valid_from=datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC),
            valid_until=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )


def test_a_quote_cannot_be_recorded_as_unknown(service, product):
    supplier = record(service)

    with pytest.raises(ValidationError, match="who says so"):
        quote(service, supplier, product, provenance="unknown")


def test_a_quote_for_a_supplier_that_does_not_exist_is_a_404(service, product, db_session):
    with pytest.raises(NotFoundError):
        service.record_quote(
            supplier_id="nope",
            product_id=product.id,
            actor="owner@amazona.local",
            correlation_id="c",
        )


# --- Capacidades del §16 -----------------------------------------------------


def declare(service, supplier, **kwargs):
    kwargs.setdefault("provenance", SupplierFactProvenance.SUPPLIER_CLAIM.value)
    return service.declare_capability(
        supplier_id=supplier.id, actor="owner@amazona.local", correlation_id="corr-3", **kwargs
    )


def test_declaring_a_capability_keeps_who_said_it(service, product):
    supplier = record(service)

    declare(service, supplier, capability="dropshipping", supported=True, note="desde 20 unidades")

    declarations = service.capability_declarations(supplier.id)
    answer = resolve(declarations, SupplyCapability.DROPSHIPPING)
    assert answer.supported is True
    assert answer.provenance is SupplierFactProvenance.SUPPLIER_CLAIM
    assert answer.note == "desde 20 unidades"


def test_a_later_declaration_does_not_erase_the_earlier_one(service, product, db_session):
    """Que un proveedor dijera una cosa en marzo y la contraria en septiembre es
    información, y machacar la fila la tiraría."""
    supplier = record(service)

    declare(service, supplier, capability="returns", supported=False)
    declare(
        service,
        supplier,
        capability="returns",
        supported=True,
        provenance="third_party_verified",
        source="auditor",
    )

    assert len(service.capability_declarations(supplier.id)) == 2
    assert resolve(
        service.capability_declarations(supplier.id), SupplyCapability.RETURNS
    ).supported is True


def test_a_capability_declared_for_one_product_does_not_leak_to_another(service, product, db_session):
    supplier = record(service)
    other = Product(name="Standing desk", category="home", created_by="owner@amazona.local")
    db_session.add(other)
    db_session.commit()

    declare(
        service,
        supplier,
        capability="direct_shipping",
        supported=False,
        product_id=product.id,
    )

    for_this = service.capability_declarations(supplier.id, product_id=product.id)
    for_other = service.capability_declarations(supplier.id, product_id=other.id)
    assert resolve(for_this, SupplyCapability.DIRECT_SHIPPING, product_id=product.id).supported is False
    assert resolve(for_other, SupplyCapability.DIRECT_SHIPPING, product_id=other.id).supported is None


def test_an_undeclared_capability_reads_as_unknown_not_as_no(service, product):
    supplier = record(service)

    answers = profile(service.capability_declarations(supplier.id))

    assert len(answers) == len(SupplyCapability)
    assert all(a.supported is None for a in answers)
    assert all(a.provenance is SupplierFactProvenance.UNKNOWN for a in answers)


def test_the_model_critical_gaps_are_listed(service, product):
    supplier = record(service)
    declare(service, supplier, capability="dropshipping", supported=True)

    missing = unanswered(service.capability_declarations(supplier.id))

    assert SupplyCapability.DROPSHIPPING not in missing
    assert SupplyCapability.EU_RETURN_ADDRESS in missing


def test_declaring_a_capability_is_audited(service, db_session):
    supplier = record(service)

    declare(service, supplier, capability="sla", supported=True)

    entry = db_session.query(AuditLog).filter_by(action="supplier.capability.declare").one()
    assert entry.after["capability"] == "sla"


# --- Riesgo ------------------------------------------------------------------


def test_the_risk_profile_of_a_real_quote_has_eight_dimensions(service, product):
    supplier = record(service, verification="third_party_verified", verified_by="Bureau of Test")
    stored = quote(
        service,
        supplier,
        product,
        unit_price=6.4,
        currency="EUR",
        destination_market="ES",
        incoterm="DDP",
        lead_time_days=3,
        transit_days=2,
    )

    risk = service.risk_profile(stored)

    assert len(risk.assessments) == len(RiskDimension)
    assert risk.of(RiskDimension.IDENTITY).level is RiskLevel.LOW
    # Origen y destino son el mismo mercado: no hay importación de por medio.
    assert risk.of(RiskDimension.GEOPOLITICAL_LOGISTICS).level is RiskLevel.LOW
    # Nadie ha declarado devoluciones: queda sin evaluar, no en «bajo».
    assert RiskDimension.LEGAL in risk.unassessed


def test_identity_verification_is_three_valued_not_two(service, product, db_session):
    """`None` significa que nadie lo ha dicho, y no es `False`: un aviso que no
    distingue eso no informa de nada."""
    silent = Supplier(name="Sin procedencia")
    db_session.add(silent)
    db_session.commit()
    unattributed = SupplierQuote(
        product_id=product.id, supplier_id=silent.id, correlation_id="c"
    )
    db_session.add(unattributed)
    db_session.commit()

    claimed = record(service)
    claimed_quote = quote(service, claimed, product)

    audited = record(
        service,
        name="Audited Co",
        verification="third_party_verified",
        verified_by="Bureau of Test",
    )
    audited_quote = quote(service, audited, product)

    assert supplier_identity_verified(db_session, unattributed) is None
    assert supplier_identity_verified(db_session, claimed_quote) is False
    assert supplier_identity_verified(db_session, audited_quote) is True
