"""Un hecho verificado de reembolso llega mientras una persona cierra ese mismo reembolso (Milestone 44, ADR 0028 §5).

`PaymentService` aplica los eventos con el pedido bloqueado, pero el observador de la acción de reembolso (la
reconciliación, la resolución humana) **no** toma ese bloqueo: cierra el reembolso y libera su reserva en su
propia transacción. Si las dos cosas se cruzan, el evento se encuentra con un reembolso que ya no está donde lo
leyó. Lo correcto es lo mismo que si hubiera llegado un instante después: el hecho verificado **se conserva como
evidencia** (`CONFLICT` o `STALE`) y el dinero no se mueve por una suposición. Lo incorrecto —y lo que ocurría—
era un `RuntimeError` (un 500 en el webhook) que dejaba el evento a medias hasta la siguiente entrega.

La ventana se fuerza de forma determinista con dos sesiones de PostgreSQL: el evento ya leyó el reembolso, la otra
sesión lo cierra y confirma, y solo entonces el evento intenta escribir.
"""

from decimal import Decimal

import pytest
from order_test_support import add_product
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    deliver,
    ingress,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions.service import ExternalActionService
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.money.money import Money
from app.orders.refunds import RefundService
from app.payments.port import PaymentEventType
from app.payments.refund_projection import refund_reference
from app.payments.service import PaymentService


def unknown_refund(engine, provider) -> tuple[str, str]:
    """Un reembolso de 10.00 cuyo resultado se perdió (`UNKNOWN_OUTCOME`, con su importe apartado)."""
    with Session(engine) as db:
        payment = start_attempt(db, add_order(db, add_product(db)), provider)
        deliver(db, provider, PaymentEventType.PAYMENT_SUCCEEDED, payment)
        provider.behaviors.append("timeout_after")
        refund = RefundService(db, settings=SIMULATION, provider=provider).request(
            payment.id, amount=Money.of("10.00", "EUR"), reason="customer_request", requester=REQUESTER
        )
        assert refund.status == "UNKNOWN_OUTCOME"
        return payment.id, refund.id


def stored_event(engine, provider, payment_id: str, refund_id: str, kind: PaymentEventType, event_id: str) -> str:
    """Un evento verificado y guardado, **sin aplicar**."""
    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        refund = db.get(Refund, refund_id)
        headers, raw = provider.simulate_event(
            kind,
            provider_payment_ref=payment.provider_payment_ref,
            provider_refund_ref=refund.provider_refund_ref,
            client_reference=refund.id,
            amount=Money.of("10.00", "EUR"),
            event_id=event_id,
        )
        real_apply = PaymentService.apply

        def died(self, event_id):
            raise KeyboardInterrupt("died between the two transactions")

        PaymentService.apply = died  # type: ignore[method-assign]
        try:
            try:
                ingress(db, provider).receive(provider.name, headers, raw)
            except KeyboardInterrupt:
                pass
        finally:
            PaymentService.apply = real_apply  # type: ignore[method-assign]
        db.rollback()
        return db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id)).one().id


def a_person_closes_it_as_failed(engine, refund_id: str) -> None:
    with Session(engine) as other:
        action = other.scalars(
            select(ExternalAction).where(ExternalAction.reference == refund_reference(refund_id))
        ).one()
        ExternalActionService(other).resolve(action, succeeded=False, actor="owner@amazona.local", reason="checked")


def apply_while(engine, event_id: str, method: str, between) -> str:
    """Aplica el evento, y justo antes de que decida sobre el reembolso hace `between()` **una vez**, en otra sesión."""
    real = getattr(PaymentService, method)
    fired: list[bool] = []

    def interleaved(self, *args, **kwargs):
        if not fired:
            fired.append(True)
            between()
        return real(self, *args, **kwargs)

    setattr(PaymentService, method, interleaved)
    try:
        with Session(engine) as db:
            outcome = PaymentService(db).apply(event_id)
        assert fired == [True], "the interleaving did not happen: the test would prove nothing"
        return outcome
    finally:
        setattr(PaymentService, method, real)


def totals(engine, payment_id: str, refund_id: str) -> tuple[str, Decimal, Decimal]:
    with Session(engine) as db:
        payment = db.get(Payment, payment_id)
        return (
            db.get(Refund, refund_id).status,
            Decimal(str(payment.refund_committed_amount)),
            Decimal(str(payment.refunded_amount)),
        )


def test_a_confirmation_that_meets_a_person_closing_the_refund_as_failed_is_kept_as_evidence_not_an_error():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id, refund_id = unknown_refund(engine, provider)
        event_id = stored_event(engine, provider, payment_id, refund_id, PaymentEventType.REFUND_SUCCEEDED, "evt_ok")

        outcome = apply_while(
            engine, event_id, "_refund_succeeded", lambda: a_person_closes_it_as_failed(engine, refund_id)
        )

        assert outcome == "CONFLICT", "the verified fact contradicts a refund closed as failed: kept as evidence"
        assert totals(engine, payment_id, refund_id) == ("FAILED", Decimal(0), Decimal(0)), (
            "no money moved on the strength of a fact that arrived mid-resolution"
        )
        with Session(engine) as db:
            assert (
                db.scalars(select(PaymentEvent).where(PaymentEvent.id == event_id)).one().processing_status
                == "CONFLICT"
            )
            assert db.scalars(select(AuditLog).where(AuditLog.action == "refund.success_after_failure")).all()


def test_a_failure_that_meets_a_person_who_already_closed_the_refund_is_stale_not_an_error():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id, refund_id = unknown_refund(engine, provider)
        event_id = stored_event(engine, provider, payment_id, refund_id, PaymentEventType.REFUND_FAILED, "evt_failed")

        outcome = apply_while(
            engine, event_id, "_refund_failed", lambda: a_person_closes_it_as_failed(engine, refund_id)
        )

        assert outcome == "STALE", "the refund is already recorded as failed: nothing left to do"
        assert totals(engine, payment_id, refund_id) == ("FAILED", Decimal(0), Decimal(0))
        with Session(engine) as db:
            assert (
                db.scalars(select(PaymentEvent).where(PaymentEvent.id == event_id)).one().processing_status == "STALE"
            )


def test_without_the_race_the_confirmation_still_settles_the_refund_once():
    with ephemeral_postgres() as engine:
        provider = ScriptedPaymentProvider()
        payment_id, refund_id = unknown_refund(engine, provider)
        event_id = stored_event(engine, provider, payment_id, refund_id, PaymentEventType.REFUND_SUCCEEDED, "evt_plain")

        with Session(engine) as db:
            outcome = PaymentService(db).apply(event_id)

        assert outcome == "APPLIED"
        assert totals(engine, payment_id, refund_id) == ("SUCCEEDED", Decimal(10), Decimal(10))


@pytest.mark.parametrize("method", ["_refund_succeeded", "_refund_failed"])
def test_the_interleaving_hook_really_runs_inside_the_decision(method):
    """Guarda de la propia prueba: si `_refund_*` cambiara de nombre, el cruce dejaría de forzarse y las
    pruebas de arriba pasarían sin probar nada."""
    assert callable(getattr(PaymentService, method))
