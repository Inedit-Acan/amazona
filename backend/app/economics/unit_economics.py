"""Unidad, pedido y adquisición no son lo mismo (Milestone 40, ADR 0018).

Hasta aquí lo eran sin que nadie lo hubiera decidido: el backend llamaba
`monthly_unit_sales` a una cifra y el frontend llamaba `monthlyOrders` a la
misma, multiplicándola por el precio de una unidad para sacar los ingresos. Es
decir, **un pedido era una unidad** por omisión, en dos vocabularios distintos, y
el techo de CAC que la pantalla enseñaba salía de esa confusión.

Un CAC es lo que cuesta conseguir **una adquisición**. Si cada pedido lleva tres
unidades, el margen que financia esa adquisición es el de tres unidades, y
calcularlo sobre una lo subestima en un 66 %.

## La cadena, con sus tres saltos explícitos

```
margen_por_unidad   = precio_venta − Σ costes variables conocidos por unidad
margen_por_pedido   = margen_por_unidad × unidades_por_pedido
techo_antes_fijos   = margen_por_pedido
coste_fijo_pedido   = costes_fijos_mensuales / pedidos_mensuales_esperados
CAC_máximo          = margen_por_pedido − coste_fijo_pedido
```

## Una adquisición es un pedido, y es una decisión declarada

Un cliente que compra tres veces reparte su coste de adquisición entre tres
pedidos, y eso es el LTV. El Milestone 40 **no lo modela**, así que fija
`pedidos_por_adquisición = 1` y lo deja escrito aquí y en el resultado. Está
declarado precisamente para que no sea una suposición silenciosa, que es lo que
era antes de este módulo.

## Nada se inventa para llegar a un número

`unidades_por_pedido` es un dato **declarado**. Un `1` que nadie ha declarado no
vale: deja el margen por pedido —y con él todo el CAC— en `NOT_EVALUABLE`, con
`units_per_order` en la lista de lo que falta. El margen por unidad sigue siendo
evaluable, porque no depende de él.

Lo mismo con `pedidos_mensuales_esperados`: sin él no hay coste fijo por pedido
ni CAC máximo, y el margen por unidad y por pedido siguen en pie. **Tres niveles
de evaluabilidad, no uno.**
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.core.errors import ValidationError
from app.economics.components import CostBreakdown
from app.money.money import Money
from app.sourcing.provenance import STORABLE, SupplierFactProvenance

#: Cuántos pedidos financia una adquisición. Uno, declarado: la compra repetida
#: es LTV y queda fuera del Milestone 40. Está aquí, con nombre, para que el día
#: que se modele se cambie en un sitio y se vea en el diff.
ORDERS_PER_ACQUISITION = Decimal(1)


class Evaluability(StrEnum):
    """Si una cifra se ha podido calcular.

    **No es un resultado económico.** `NOT_EVALUABLE` dice «no se puede saber»;
    un margen negativo dice «se sabe, y es malo». Confundirlos descartaría
    productos buenos por falta de un dato administrativo, así que la distinción
    viaja en el tipo y no en un comentario.
    """

    EVALUABLE = "evaluable"
    NOT_EVALUABLE = "not_evaluable"


@dataclass(frozen=True)
class DeclaredQuantity:
    """Una cantidad que alguien afirma, con quién la afirma.

    Existe para que un `1` no pueda entrar sin firma. `value=None` es
    desconocido; un valor con procedencia `UNKNOWN` no se puede construir.
    """

    value: Decimal | None = None
    provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    source: str | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            if self.provenance is not SupplierFactProvenance.UNKNOWN:
                raise ValidationError(
                    f"an absent quantity cannot be {self.provenance}: "
                    "there is nothing to attribute"
                )
            return
        if not isinstance(self.value, Decimal):
            raise ValidationError("a declared quantity must be a Decimal, not a float")
        if self.value <= 0:
            raise ValidationError(f"a declared quantity must be positive, got {self.value}")
        if self.provenance not in STORABLE:
            raise ValidationError(
                "a quantity with a value must say who says so: a 1 that nobody declared "
                "is the silent assumption Milestone 40 removes"
            )

    @property
    def known(self) -> bool:
        return self.value is not None

    @classmethod
    def unknown(cls) -> "DeclaredQuantity":
        return cls()

    @classmethod
    def declared(cls, value: int | Decimal, *, source: str) -> "DeclaredQuantity":
        """Lo que afirma el operador."""
        return cls(
            value=Decimal(value),
            provenance=SupplierFactProvenance.DECLARED,
            source=source,
        )

    @classmethod
    def simulated(cls, value: int | Decimal, *, source: str) -> "DeclaredQuantity":
        """Lo que trae un fixture. Los datos de demostración pueden usar 1 por
        defecto **y quedan marcados como simulados**, nunca como declarados."""
        return cls(
            value=Decimal(value),
            provenance=SupplierFactProvenance.SIMULATED,
            source=source,
        )


@dataclass(frozen=True)
class UnitEconomicsInput:
    """Lo que hace falta para calcular. Todo en la misma moneda, garantizado por
    `Money` antes de llegar aquí."""

    sale_price: Money
    breakdown: CostBreakdown
    #: Cuántas unidades lleva un pedido. Desconocido ⇒ no hay margen por pedido.
    units_per_order: DeclaredQuantity = field(default_factory=DeclaredQuantity.unknown)
    #: Cuántos pedidos se esperan al mes. Desconocido ⇒ no hay CAC máximo.
    expected_monthly_orders: DeclaredQuantity = field(default_factory=DeclaredQuantity.unknown)
    #: Costes fijos mensuales. `None` ⇒ tampoco hay CAC máximo.
    monthly_fixed_costs: Money | None = None
    #: Margen objetivo por pedido, para cuando alguien lo fije. **El Milestone 40
    #: no lo calcula ni lo supone**: el hueco está aquí para que el día que se
    #: decida un beneficio mínimo entre por un sitio y no por cinco.
    target_margin_per_order: Money | None = None

    def __post_init__(self) -> None:
        if self.monthly_fixed_costs is not None:
            # Provoca CurrencyMismatchError si no coinciden: más vale aquí que
            # dentro de una resta a mitad del cálculo.
            self.sale_price - self.monthly_fixed_costs * 0


@dataclass(frozen=True)
class UnitEconomicsResult:
    """El margen y el techo de CAC, cada cifra con su evaluabilidad."""

    currency: str

    contribution_margin_per_unit: Money | None
    #: Fracción del precio de venta. Sin moneda, porque un porcentaje no la tiene.
    contribution_margin_percent: Decimal | None
    contribution_margin_per_order: Money | None
    #: Lo que se podría pagar por una adquisición **antes** de cubrir los costes
    #: fijos. Es el margen por pedido: útil para saber si el producto aguanta
    #: adquisición de pago antes de mirar la estructura.
    breakeven_cac_before_fixed_costs: Money | None
    allocated_fixed_cost_per_order: Money | None
    #: Lo que podríamos permitirnos pagar por una adquisición. **No dice lo que
    #: costará**: eso es CAC medido y queda fuera del Milestone 40.
    max_breakeven_cac: Money | None

    margin_evaluability: Evaluability
    cac_evaluability: Evaluability
    #: Qué falta, por su nombre. Es la lista que hay que rellenar para que el
    #: resultado exista, y por eso va en el resultado y no en un log.
    missing_inputs: tuple[str, ...] = ()
    #: Costes opcionales que nadie ha declarado. No impiden el cálculo; el
    #: margen es optimista en esa cantidad y el resultado lo dice.
    omitted_costs: tuple[str, ...] = ()
    #: La procedencia más floja de lo que se sumó. Un suelo, no una nota.
    weakest_provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    #: Cuántos pedidos financia una adquisición. Uno, declarado.
    orders_per_acquisition: Decimal = ORDERS_PER_ACQUISITION


def evaluate(inputs: UnitEconomicsInput) -> UnitEconomicsResult:
    """La cadena entera, parándose donde deje de haber datos.

    No hay ningún camino por el que una cifra ausente se convierta en cero. Lo
    que no se puede calcular sale `None` y su nombre sale en `missing_inputs`.
    """
    currency = inputs.sale_price.currency
    missing: list[str] = []
    blocking = inputs.breakdown.blocking

    # --- margen por unidad -------------------------------------------------
    if blocking:
        missing.extend(concept.value for concept in blocking)
        return UnitEconomicsResult(
            currency=currency,
            contribution_margin_per_unit=None,
            contribution_margin_percent=None,
            contribution_margin_per_order=None,
            breakeven_cac_before_fixed_costs=None,
            allocated_fixed_cost_per_order=None,
            max_breakeven_cac=None,
            margin_evaluability=Evaluability.NOT_EVALUABLE,
            cac_evaluability=Evaluability.NOT_EVALUABLE,
            missing_inputs=tuple(missing),
            omitted_costs=tuple(c.value for c in inputs.breakdown.omitted),
            weakest_provenance=inputs.breakdown.weakest_provenance,
        )

    margin_per_unit = inputs.sale_price - inputs.breakdown.total_cost(currency=currency)
    margin_percent = (
        margin_per_unit.ratio_to(inputs.sale_price) if not inputs.sale_price.is_zero else None
    )

    # --- margen por pedido -------------------------------------------------
    units = inputs.units_per_order
    if not units.known:
        # Un `1` no declarado no vale. Sin esto no hay pedido, y sin pedido no
        # hay nada que un CAC pueda financiar.
        missing.append("units_per_order")
        margin_per_order = None
    else:
        assert units.value is not None
        margin_per_order = margin_per_unit * units.value

    # --- coste fijo por pedido y CAC máximo --------------------------------
    orders = inputs.expected_monthly_orders
    fixed = inputs.monthly_fixed_costs
    allocated: Money | None = None
    if not orders.known:
        missing.append("expected_monthly_orders")
    if fixed is None:
        missing.append("monthly_fixed_costs")
    if orders.known and fixed is not None:
        assert orders.value is not None
        allocated = fixed / orders.value

    max_cac = (
        margin_per_order - allocated
        if margin_per_order is not None and allocated is not None
        else None
    )

    return UnitEconomicsResult(
        currency=currency,
        contribution_margin_per_unit=margin_per_unit,
        contribution_margin_percent=margin_percent,
        contribution_margin_per_order=margin_per_order,
        breakeven_cac_before_fixed_costs=margin_per_order,
        allocated_fixed_cost_per_order=allocated,
        max_breakeven_cac=max_cac,
        margin_evaluability=Evaluability.EVALUABLE,
        cac_evaluability=(
            Evaluability.EVALUABLE if max_cac is not None else Evaluability.NOT_EVALUABLE
        ),
        missing_inputs=tuple(missing),
        omitted_costs=tuple(c.value for c in inputs.breakdown.omitted),
        weakest_provenance=inputs.breakdown.weakest_provenance,
    )
