"""Cuándo un pedido necesita que una persona lo mire (Milestone 44, ADR 0028 §4).

`attention_required` **se calcula al leer**, a partir del estado de las tablas; no es una columna que pueda quedar
obsoleta, y calcularlo no escribe nada (un `GET` no escribe, I10). Cada razón es un código estable que la pantalla
y las pruebas pueden nombrar.

Las razones las aportan los dominios que existen: los pagos (captura duplicada, captura sobre un pedido cancelado,
captura de un importe distinto, intento abierto con el pedido ya cobrado, resultado desconocido) y el fulfillment
(compra o envío de resultado desconocido, envío reintentado sin éxito). Lo que no existe aún no aporta ninguna.
"""

from sqlalchemy.orm import Session

from app.db.models.order import Order


def attention_reasons(db: Session, order: Order) -> list[str]:
    """Las razones, en un orden estable. Vacío = nada que mirar."""
    reasons: list[str] = []
    return reasons
