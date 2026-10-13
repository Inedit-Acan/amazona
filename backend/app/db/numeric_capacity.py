"""Qué cabe en una columna numérica del modelo (M46, Commit 5c).

`Money` representa mucho más de lo que algunas columnas pueden guardar: un `Numeric(12, 4)` solo admite ocho cifras
enteras, y un `Numeric(12, 2)` diez. En SQLite no se nota (no impone la precisión); en PostgreSQL un importe válido
para `Money` pero fuera de la columna sale como un error de base de datos (500) o, peor, deja una sesión en
`PendingRollbackError` y un trabajo atascado. Este módulo lee la capacidad **de las propias columnas declaradas**:
no hay un solo número escrito a mano, y si una columna se amplía con una migración la regla la sigue.

**No es un máximo comercial ni fiscal.** Es lo que el esquema actual puede guardar. La política de límites de negocio
sigue sin definirse; cuando exista, esto seguirá siendo el suelo técnico por debajo de ella.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ColumnElement

from app.core.errors import ValidationError

#: `INTEGER` de PostgreSQL (4 bytes con signo). SQLAlchemy `Integer` no declara su anchura; la base de datos de
#: producción sí.
INTEGER_MIN = -(2**31)
INTEGER_MAX = 2**31 - 1


class ValueNotStorableError(ValidationError):
    """Un valor que las columnas del modelo no pueden guardar: dos entradas válidas cuyo resultado no cabe.

    Se lanza **antes** de escribir nada. El mensaje no nombra tablas ni columnas.
    """


def numeric_capacity(column: ColumnElement[Any]) -> Decimal | None:
    """El mayor valor absoluto que guarda una columna `Numeric(p, s)`: `10^(p-s) - 10^-s`. `None` si no está acotada."""
    column_type = column.type
    if not isinstance(column_type, sa.Numeric) or column_type.precision is None:
        return None
    scale = column_type.scale or 0
    return Decimal(10) ** (column_type.precision - scale) - Decimal(1).scaleb(-scale)


def fits_column(value: Any, column: ColumnElement[Any]) -> bool:
    """Si `value` cabe en `column`. Un `NULL` siempre cabe. Un tipo no acotado también."""
    if value is None:
        return True
    column_type = column.type
    if isinstance(column_type, sa.Integer):
        return isinstance(value, int) and INTEGER_MIN <= value <= INTEGER_MAX
    capacity = numeric_capacity(column)
    if capacity is None:
        return True
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if not number.is_finite():
        return False
    scale = getattr(column_type, "scale", None) or 0
    try:
        stored = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    return abs(stored) <= capacity


def require_row_fits_storage(row: Any) -> None:
    """Falla en voz alta si algún `Numeric`/`Integer` de la fila no cabe en su columna. Léase **antes** de `db.add`."""
    for attribute in sa.inspect(row).mapper.column_attrs:
        column = attribute.columns[0]
        if isinstance(column.type, (sa.Numeric, sa.Integer)) and not fits_column(getattr(row, attribute.key), column):
            raise ValueNotStorableError(
                "a monetary result of this operation is too large to be stored: the values received are "
                "individually valid but not together"
            )
