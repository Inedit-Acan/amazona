"""Paginar los pedidos sin truncar en silencio (M45, P2-2).

`GET /api/orders` devolvía una lista y se acabó: quien pedía 500 y recibía 500 no podía saber si había un pedido
501. Ahora devuelve una **página** que lo dice (`has_more`) y cómo seguir (`next_cursor`).

## Por qué un cursor y no un `offset`

Los pedidos se listan del más reciente al más antiguo. Un pedido nuevo entra **por arriba**: con `offset`, cada
pedido nuevo empuja a los demás una posición y la página siguiente repite filas de la anterior (un duplicado), y
cuantos más se crean mientras alguien navega, más repite. Un cursor es una **posición** en el orden (`created_at`,
`id`), no un número de fila: lo que se crea después queda fuera del recorrido en curso y nada se repite ni se salta.

## El orden y el cursor

El orden es `created_at DESC, id ASC`: total y determinista (el `id` desempata a igual instante, y es único). El
cursor es el último elemento de la página, `(created_at, id)`, y la página siguiente son las filas **estrictamente
posteriores a él en ese orden**:

    created_at < :t   OR   (created_at = :t AND id > :id)

Se codifica opaco (`base64url` de un JSON versionado) para que el cliente no lo interprete: es un valor que se devuelve
tal cual. No lleva ningún dato del pedido salvo su instante y su identificador, y se **valida** al recibirlo: lo que no
es un cursor emitido por este formato es un error de validación (422), nunca una página vacía ni una consulta distinta.
Los valores van siempre como parámetros enlazados: no hay forma de inyectar nada.

## Lo que esto no garantiza

No es una instantánea. Un pedido que se confirme **después** de que el recorrido pasara por su instante (una transacción
lenta con un `created_at` anterior) no aparece hasta volver a empezar; y los estados que cambian (un pedido que se paga)
se leen en el momento de cada página. Ver ADR 0028 y el handoff del Commit 3 de M45.
"""

import base64
import binascii
import datetime
import json
import re
from dataclasses import dataclass

from app.core.errors import ValidationError
from app.db.models.order import Order

#: Cuántos pedidos devuelve una página si no se pide otra cosa.
DEFAULT_PAGE_SIZE = 100
#: El máximo por página. Cada pedido de la página cuesta ~8 consultas (medido: 100 pedidos = 801 consultas, ~0,5 s;
#: 500 = 4 001, ~3 s): un tope bajo acota el coste de una petición. Un recorrido completo sigue `next_cursor`.
MAX_PAGE_SIZE = 200

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 256
_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,36}$")


class InvalidCursorError(ValidationError):
    """El cursor no es uno que este servicio emitiera (o está dañado). Nunca se interpreta «a medias»."""


@dataclass(frozen=True)
class OrderCursor:
    """La posición en el orden `created_at DESC, id ASC`: el último pedido ya entregado."""

    created_at: datetime.datetime
    order_id: str

    def encode(self) -> str:
        document = {"v": _CURSOR_VERSION, "t": self.created_at.isoformat(), "i": self.order_id}
        raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "OrderCursor":
        if not value or len(value) > _MAX_CURSOR_LENGTH or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise InvalidCursorError("the cursor is not valid: use the next_cursor of a previous page as it came")
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict) or document.get("v") != _CURSOR_VERSION:
                raise ValueError("unknown cursor version")
            created_at = datetime.datetime.fromisoformat(str(document["t"]))
            order_id = document["i"]
            if not isinstance(order_id, str) or not _ID_PATTERN.fullmatch(order_id):
                raise ValueError("bad id")
        except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
            raise InvalidCursorError(
                "the cursor is not valid: use the next_cursor of a previous page as it came"
            ) from exc
        return cls(created_at=created_at, order_id=order_id)


@dataclass(frozen=True)
class OrderPageResult:
    orders: list[Order]
    has_more: bool
    next_cursor: str | None
