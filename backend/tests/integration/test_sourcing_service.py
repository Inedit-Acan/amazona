import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.sourcing.service import SourcingService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_product(db_session: Session) -> Product:
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def test_run_sourcing_persists_a_supplier_and_quote_per_candidate(db_session: Session):
    product = _make_product(db_session)
    service = SourcingService(db_session)

    quotes = service.run_sourcing(
        product_id=product.id,
        category="electronics",
        destination_region="mexico",
        max_results=3,
        correlation_id="corr-1",
    )

    assert 1 <= len(quotes) <= 3
    persisted_suppliers = db_session.query(Supplier).all()
    assert len(persisted_suppliers) == len(quotes)

    persisted_quotes = db_session.query(SupplierQuote).filter_by(correlation_id="corr-1").all()
    assert len(persisted_quotes) == len(quotes)
    assert all(q.product_id == product.id for q in persisted_quotes)
    assert all(q.analysis_type == "sourcing" for q in persisted_quotes)


def test_run_sourcing_audits_the_run(db_session: Session):
    product = _make_product(db_session)
    service = SourcingService(db_session)

    service.run_sourcing(
        product_id=product.id,
        category="electronics",
        destination_region="mexico",
        max_results=3,
        correlation_id="corr-2",
    )

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-2").all()
    assert any(e.action == "sourcing.run" for e in entries)


def test_run_sourcing_raises_not_found_for_an_unknown_product(db_session: Session):
    service = SourcingService(db_session)

    with pytest.raises(NotFoundError):
        service.run_sourcing(
            product_id=new_id(),
            category="electronics",
            destination_region="mexico",
            max_results=3,
            correlation_id="corr-3",
        )


def test_run_sourcing_twice_reuses_existing_suppliers_but_creates_new_quotes(db_session: Session):
    product = _make_product(db_session)
    service = SourcingService(db_session)

    first_quotes = service.run_sourcing(
        product_id=product.id,
        category="electronics",
        destination_region="mexico",
        max_results=3,
        correlation_id="corr-4",
    )
    second_quotes = service.run_sourcing(
        product_id=product.id,
        category="electronics",
        destination_region="mexico",
        max_results=3,
        correlation_id="corr-5",
    )

    assert db_session.query(Supplier).count() == len(first_quotes)
    assert db_session.query(SupplierQuote).count() == len(first_quotes) + len(second_quotes)


def test_run_sourcing_with_unknown_category_persists_nothing(db_session: Session):
    product = _make_product(db_session)
    service = SourcingService(db_session)

    quotes = service.run_sourcing(
        product_id=product.id,
        category="does-not-exist",
        destination_region="mexico",
        max_results=3,
        correlation_id="corr-6",
    )

    assert quotes == []
    assert db_session.query(SupplierQuote).count() == 0
