"""La aritmética de los reembolsos sobre un cobro (Milestone 44, ADR 0028 §5).

Mismo patrón que el libro de presupuesto (ADR 0023): **comprobar y escribir en una sola sentencia**. Evaluar primero
y reservar después dejaría que dos reembolsos a la vez vieran el mismo saldo libre. Aquí cada movimiento es un
`UPDATE … WHERE` cuya condición *es* el límite, y el `CHECK` de la tabla (`refunded <= refund_committed <= captured`)
es el respaldo si alguien se saltara este módulo.

- `reserve`: aparta un importe de lo reembolsable (`refund_committed_amount += a`) si cabe en lo cobrado;
- `settle`: el reembolso ocurrió (`refunded_amount += a`); su importe ya estaba apartado;
- `release`: el reembolso no ocurrió (`refund_committed_amount -= a`): **solo** cuando se sabe que no hubo efecto.
  Un resultado desconocido **no** libera.
"""

from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.models.payment import Payment
from app.payments.domain import CAPTURED_PAYMENT_STATUSES


def _execute(db: Session, statement) -> CursorResult:
    result = db.execute(statement.execution_options(synchronize_session=False))
    assert isinstance(result, CursorResult)
    return result


def reserve(db: Session, payment_id: str, amount: Decimal) -> bool:
    """Aparta `amount` de lo reembolsable. `False` si no cabe (o el cobro no tiene dinero capturado)."""
    result = _execute(
        db,
        update(Payment)
        .where(
            Payment.id == payment_id,
            Payment.status.in_(CAPTURED_PAYMENT_STATUSES),
            Payment.captured_amount - Payment.refund_committed_amount >= amount,
        )
        .values(refund_committed_amount=Payment.refund_committed_amount + amount),
    )
    return result.rowcount == 1


def settle(db: Session, payment_id: str, amount: Decimal) -> bool:
    """El reembolso ocurrió: lo reembolsado sube. Su importe ya estaba apartado, así que debe caber en lo apartado."""
    result = _execute(
        db,
        update(Payment)
        .where(Payment.id == payment_id, Payment.refund_committed_amount - Payment.refunded_amount >= amount)
        .values(refunded_amount=Payment.refunded_amount + amount),
    )
    return result.rowcount == 1


def release(db: Session, payment_id: str, amount: Decimal) -> bool:
    """El reembolso no ocurrió: se devuelve lo apartado. Nunca más de lo que está apartado sin reembolsar."""
    result = _execute(
        db,
        update(Payment)
        .where(Payment.id == payment_id, Payment.refund_committed_amount - Payment.refunded_amount >= amount)
        .values(refund_committed_amount=Payment.refund_committed_amount - amount),
    )
    return result.rowcount == 1


def reserve_and_settle(db: Session, payment_id: str, amount: Decimal) -> bool:
    """Un reembolso que el proveedor ya hizo y que no iniciamos nosotros: cabe y se cuenta de una vez."""
    result = _execute(
        db,
        update(Payment)
        .where(
            Payment.id == payment_id,
            Payment.status.in_(CAPTURED_PAYMENT_STATUSES),
            Payment.captured_amount - Payment.refund_committed_amount >= amount,
        )
        .values(
            refund_committed_amount=Payment.refund_committed_amount + amount,
            refunded_amount=Payment.refunded_amount + amount,
        ),
    )
    return result.rowcount == 1
