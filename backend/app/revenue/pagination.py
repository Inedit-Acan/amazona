"""El cursor de la lista de entradas del registro de ingresos (M45, ADR 0030).

Las entradas se listan de la más reciente a la más antigua: `occurred_at DESC, id DESC`, un orden total y determinista
(el `id` desempata a igual instante y es único). El cursor es una **posición** en ese orden, la última entrada ya
entregada `(occurred_at, id)`, y la página siguiente son las filas **estrictamente anteriores** a ella:

    (occurred_at, id) < (:t, :id)

Se escribe como comparación de filas (no como `a < x OR (a = x AND id < y)`) porque PostgreSQL la resuelve con una sola
exploración del índice `(occurred_at, id)`: medido sobre 990 000 entradas, la página profunda pasa de 205-454 ms con el
`OR` a ~1 ms. Una entrada nueva entra por arriba y no mueve lo que ya se recorrió: ni duplica ni salta filas.

El cursor es opaco (`base64url` de un JSON versionado), no lleva ningún dato de la entrada salvo su instante y su
identificador, y se **valida** al recibirlo: lo que no es un cursor emitido por este formato es un error de validación
(422), nunca una página vacía ni otra consulta. Los valores van siempre como parámetros enlazados.

No es una instantánea: una entrada que se escriba **después** de que el recorrido pasara por su instante (una
transacción lenta con un `occurred_at` anterior) no aparece hasta volver a empezar.
"""

import base64
import binascii
import datetime
import json
import re
from dataclasses import dataclass

from app.core.errors import ValidationError

#: Cuántas entradas devuelve una página si no se pide otra cosa.
DEFAULT_PAGE_SIZE = 100
#: El máximo por página. Sin uniones ni consultas por fila: el coste de una página es el de leer su rango del índice.
MAX_PAGE_SIZE = 200

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 256
_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,36}$")
_MESSAGE = "the cursor is not valid: use the next_cursor of a previous page as it came"


class InvalidCursorError(ValidationError):
    """El cursor no es uno que este servicio emitiera (o está dañado). Nunca se interpreta «a medias»."""


@dataclass(frozen=True)
class EntryCursor:
    occurred_at: datetime.datetime
    entry_id: str

    def encode(self) -> str:
        document = {"v": _CURSOR_VERSION, "t": self.occurred_at.isoformat(), "i": self.entry_id}
        raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "EntryCursor":
        if not value or len(value) > _MAX_CURSOR_LENGTH or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise InvalidCursorError(_MESSAGE)
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict) or document.get("v") != _CURSOR_VERSION:
                raise ValueError("unknown cursor version")
            occurred_at = datetime.datetime.fromisoformat(str(document["t"]))
            entry_id = document["i"]
            if not isinstance(entry_id, str) or not _ID_PATTERN.fullmatch(entry_id):
                raise ValueError("bad id")
        except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
            raise InvalidCursorError(_MESSAGE) from exc
        if occurred_at.tzinfo is None:
            raise InvalidCursorError(_MESSAGE)
        return cls(occurred_at=occurred_at, entry_id=entry_id)
