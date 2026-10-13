"""La frontera numérica de entrada compartida por economics, pipeline y tipos de cambio (M46, Commit 5c).

Un solo sitio para que dos endpoints con la misma semántica no tengan dos contratos que divergen por accidente:
`sale_price` y `monthly_fixed_costs` significan lo mismo en `POST /api/economics/runs` y en `POST /api/pipeline/runs`
(el pipeline se los pasa tal cual a `run_analysis`), así que pasan por **las mismas** precondiciones.

Reglas, todas sobre cantidades de negocio de entrada:
  * finitas: `NaN`, `Infinity` y `-Infinity` no son cantidades;
  * con su signo: el precio estrictamente positivo **como importe** (`MIN_SALE_PRICE`), los costes fijos, el
    presupuesto diario y el volumen mensual `>= 0`;
  * **representables**: lo que `Money` puede representar (`Money.can_represent`) y, para el presupuesto diario, lo
    que cabe en la columna donde se guarda el gasto (`numeric_capacity`). Ninguna de las dos cosas es un máximo
    comercial ni fiscal: son el suelo técnico del sistema actual. La política de límites de negocio sigue pendiente.

Un fallo de estas reglas es un `ValidationError` del dominio: 422 `{"detail": "<cadena>"}` que **nombra el campo y no
repite lo recibido**. Se hace aquí, como precondición explícita y antes de crear nada, y no con `Field(ge=...)`: el 422
de esquema repite el valor en su cuerpo y un `NaN` no se puede escribir en JSON (ver `validation_body.py`).

Los tipos `StrictFloat`/`StrictInt` de los esquemas rechazan `bool` y cadenas numéricas (`true`, `"20"`): un booleano
no es una cantidad. Solo se aplican a los campos de estos tres esquemas.
"""

import math
from decimal import Decimal

from app.core.errors import ValidationError
from app.db.models.external_action import ExternalAction
from app.db.numeric_capacity import fits_column
from app.money.money import INTERNAL_PLACES, Money

#: El menor precio de venta que `Money` distingue de cero. `Money` guarda `INTERNAL_PLACES` decimales y redondea
#: con ROUND_HALF_UP: 0,00005 pasa a 0,0001 y todo lo que está por debajo se queda en 0,0000, que es un precio
#: cero. Un precio es estrictamente positivo **como importe**, no solo como `float`. No es una unidad mínima comercial
#: por divisa: es una precondición coherente con la representación monetaria actual.
MIN_SALE_PRICE = float(Decimal(5).scaleb(-(INTERNAL_PLACES + 1)))

#: Cuántos resultados pide una investigación, un sourcing o una ejecución del pipeline. Una sola fuente: antes el
#: `1..20` estaba escrito en `research`, `sourcing` y (sin límite) distinto en `pipeline`.
MAX_RESULTS_MIN = 1
MAX_RESULTS_MAX = 20

#: Dónde acaba el gasto de un presupuesto diario (`ExternalAction.amount`): su columna fija lo que cabe.
_SPEND_COLUMN = ExternalAction.__table__.c.amount


def _money_problem(name: str, value: float, *, minimum: float, requirement: str) -> str | None:
    """El motivo por el que `value` no vale para `name`, o `None`. Nunca incluye el valor."""
    if not math.isfinite(value) or value < minimum or not Money.can_represent(value):
        return f"{name} must be a finite amount {requirement} that Money can represent"
    return None


def require_amounts(
    *,
    sale_price: float | None = None,
    monthly_fixed_costs: float | None = None,
    daily_budget: float | None = None,
    monthly_unit_sales_base: float | None = None,
) -> None:
    """Las precondiciones de cantidad de un endpoint, todas a la vez, antes de crear nada.

    Cada argumento que se pasa se comprueba; `None` no se comprueba (el campo no existe en ese endpoint o es
    opcional y no vino). Si falla más de uno, un solo mensaje los nombra a todos.
    """
    problems: list[str | None] = []
    if sale_price is not None:
        problems.append(
            _money_problem(
                "sale_price",
                sale_price,
                minimum=MIN_SALE_PRICE,
                requirement=f"of at least {format(Decimal(str(MIN_SALE_PRICE)), 'f')} (a smaller one rounds to zero)",
            )
        )
    if monthly_fixed_costs is not None:
        problems.append(
            _money_problem("monthly_fixed_costs", monthly_fixed_costs, minimum=0.0, requirement="of zero or more")
        )
    if daily_budget is not None:
        problem = _money_problem("daily_budget", daily_budget, minimum=0.0, requirement="of zero or more")
        if problem is None and not fits_column(daily_budget, _SPEND_COLUMN):
            problem = "daily_budget must be a finite amount of zero or more that can be stored as spend"
        problems.append(problem)
    if monthly_unit_sales_base is not None:
        if not math.isfinite(monthly_unit_sales_base) or monthly_unit_sales_base < 0:
            problems.append("monthly_unit_sales_base must be a finite number of zero or more")
    found = [problem for problem in problems if problem]
    if found:
        raise ValidationError("; ".join(found))
