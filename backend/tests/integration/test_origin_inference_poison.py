"""El origen del dinero no depende de nada que no sea el proveedor que lo declara (Milestone 46, ADR 0031 §4, §11, §12).

La guarda de `tests/unit/test_money_provenance_architecture.py` lee el **código**. Esta prueba lo ejecuta: «envenena»
todas las señales con las que se podría deducir el origen —`ProviderBinding.is_simulated`, los métodos del registro que
leen la configuración— para que cualquier lectura **falle en voz alta**, y recorre el flujo entero del dinero (abrir el
cobro, capturar, duplicar, reembolsar, reconciliar). Si algún camino las leyera, la prueba se rompería; si no, el origen
se decide en otro sitio. Además se contradice a propósito lo que podría usarse como pista:

- el pedido (`Order.is_simulated` y su `customer_ref`) se invierte por SQL **después** de abrir el cobro;
- la configuración dice que el proveedor de pagos es otro (`payments_provider`);
- el proveedor se llama como el simulador mientras declara otro origen.

Y el origen no cambia en ningún caso. Esto es lo que mata, de verdad, una mutación «usar `ProviderBinding.is_simulated`
en la ruta del dinero» (M15 del ADR).
"""

import pytest
from payment_test_support import (
    SIMULATION,
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    deliver,
    events,
    ingress,
    start_attempt,
)
from revenue_test_support import (
    REFUND_SUCCEEDED,
    SUCCEEDED,
    confirm_refund,
    duplicate_pair,
    entries,
    new_order,
    refund_of,
)
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.order import Order
from app.db.models.payment import Payment
from app.integrations.ports import ProviderKind
from app.integrations.registry import ProviderBinding, ProviderRegistry
from app.money.money import Money
from app.reconciliation.report import build_status
from app.revenue.check import check_ledger

ORIGINS = {"mock": MockPaymentProvider, "sandbox": SandboxPaymentProvider, "real": RealPaymentProvider}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def poison(monkeypatch) -> None:
    """Toda lectura de una señal «es simulado» o «lo que dice la configuración» falla."""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the origin of money was inferred from a simulation signal instead of the provider")

    monkeypatch.setattr(ProviderBinding, "is_simulated", property(forbidden))
    for method in ("kind_for", "binding_for", "bindings"):
        monkeypatch.setattr(ProviderRegistry, method, forbidden)


def the_whole_money_flow(db: Session, provider, name: str) -> Payment:
    """Abrir, capturar, duplicar, reembolsar y mirar la reconciliación: todo lo que toca el dinero."""
    order = new_order(db, name=name, customer=f"sim_{name}")
    first, second = duplicate_pair(db, provider, order)
    confirm_refund(db, provider, refund_of(db, provider, first, "20.00"))
    confirm_refund(db, provider, refund_of(db, provider, second, "50.00", reason="duplicate_capture"))
    build_status(db, SIMULATION)
    return first


@pytest.mark.parametrize("origin", ORIGINS)
def test_the_money_flow_never_reads_a_simulation_signal_and_still_knows_its_origin(
    db: Session, origin: str, monkeypatch
):
    poison(monkeypatch)
    provider = ORIGINS[origin]()

    first = the_whole_money_flow(db, provider, "Widget")

    assert first.provider_kind == origin
    assert {e.provider_kind for e in entries(db)} == {origin} and len(entries(db)) == 4
    assert {e.provider_kind for e in events(db)} == {origin}
    status = check_ledger(db)
    assert status["divergences"]["count"] == 0 and status["outside_ledger"]["count"] == 0


def test_the_poison_really_poisons_it_is_not_a_no_op(monkeypatch):
    poison(monkeypatch)
    binding = ProviderBinding(domain=None, kind=ProviderKind.MOCK, name="x")  # type: ignore[arg-type]
    with pytest.raises(AssertionError, match="inferred"):
        _ = binding.is_simulated
    with pytest.raises(AssertionError, match="inferred"):
        ProviderRegistry(Settings(_env_file=None)).kind_for(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("origin", ORIGINS)
@pytest.mark.parametrize("flip_to", [True, False], ids=["order-says-simulated", "order-says-not-simulated"])
def test_the_order_context_flipped_after_the_payment_opened_does_not_change_any_origin(
    db: Session, origin: str, flip_to: bool
):
    provider = ORIGINS[origin]()
    order = new_order(db)
    payment = start_attempt(db, order, provider)
    db.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(is_simulated=flip_to, customer_ref="sim_flipped" if flip_to else "cust_flipped")
    )
    db.commit()

    assert deliver(db, provider, SUCCEEDED, payment).outcome == "applied"
    confirm_refund(db, provider, refund_of(db, provider, payment, "10.00"))

    assert {e.provider_kind for e in entries(db)} == {origin} and len(entries(db)) == 2
    assert {e.provider_kind for e in events(db)} == {origin}
    assert db.get(Payment, payment.id).provider_kind == origin


@pytest.mark.parametrize("configured", [ProviderKind.MOCK, ProviderKind.SANDBOX, ProviderKind.REAL])
@pytest.mark.parametrize("origin", ORIGINS)
def test_what_the_configuration_says_about_the_payments_provider_is_not_the_origin(
    db: Session, origin: str, configured: ProviderKind
):
    """El cobro se abre con los ajustes por defecto (con otro proveedor configurado el despliegue deja de ser una
    simulación y entran las puertas legal y de roles, que no tienen que ver con el origen). Después, la recepción de
    eventos corre con unos ajustes que **dicen otro proveedor**: el origen es el del adaptador que se guardó."""
    provider = ORIGINS[origin]()
    payment = start_attempt(db, new_order(db), provider)
    settings = Settings(_env_file=None, payments_provider=configured)

    headers, raw = signed_capture(provider, payment)
    result = ingress(db, provider, settings=settings).receive(provider.name, headers, raw)

    assert result.outcome == "applied"
    assert payment.provider_kind == origin and [e.provider_kind for e in entries(db)] == [origin]
    confirm_refund(db, provider, refund_of(db, provider, payment, "10.00"))
    refund_headers, refund_raw = provider.simulate_event(
        REFUND_SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        provider_refund_ref="re_by_provider",
        client_reference=payment.id,
        amount=Money.of("5.00", "EUR"),
        event_id="evt_provider_refund",
    )
    again = ingress(db, provider, settings=settings).receive(provider.name, refund_headers, refund_raw)
    assert again.outcome == "applied"
    assert {e.provider_kind for e in entries(db)} == {origin} and len(entries(db)) == 3
    assert {e.provider_kind for e in events(db)} == {origin}


def signed_capture(provider, payment: Payment):
    return provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of(str(payment.amount), payment.currency),
    )
