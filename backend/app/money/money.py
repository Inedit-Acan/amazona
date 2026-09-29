"""Un importe y su moneda, inseparables (Milestone 40, ADR 0018).

El Milestone 39 dejó una cotización con moneda y una regla: **no se convierte
entre monedas**. Lo que no dejó es nada que impidiera sumarlas igualmente. El
coste de aterrizaje del mock está en dólares, el precio de venta se razona en
euros, y el margen se calculaba restando el uno del otro — con un aviso en la
lista de riesgos y el número mal.

Un aviso no es una salvaguarda. Este módulo convierte esa regla en un tipo:
**dos importes de monedas distintas no se pueden restar**, y el intento falla
donde se escribe, no donde se enseña.

## Por qué `Decimal` y no `float`

Porque `0.1 + 0.2` vale `0.30000000000000004` en coma flotante, y un céntimo
perdido por unidad son cuarenta euros en un pedido de cuatro mil. El resto del
repositorio usa `float` y **no se migra en este milestone**: lo que hay es una
frontera declarada en `serialization.py`, con una regla para cruzarla en cada
sentido, y la deuda legacy escrita en la ADR.

## Redondeo, en un solo sitio

Cuatro decimales por dentro —un coste unitario de 0,0042 € existe, lo medimos en
el Milestone 39— y dos al presentar. **Se redondea al final**, nunca entre dos
sumas: redondear a mitad de camino mete el error que se quería evitar.

`ROUND_HALF_UP` y no el `ROUND_HALF_EVEN` que Python trae por defecto, porque es
lo que hace una factura y lo que espera quien comprueba una cuenta a mano.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import ValidationError
from app.sourcing.trade_terms import currency_for

#: Decimales de la aritmética interna. Cuatro, no dos: un coste logístico por
#: unidad de 0,0042 € es real y redondearlo a dos lo convertiría en cero.
INTERNAL_PLACES = 4

#: Decimales al presentar. Se aplica **al final**, nunca entre dos operaciones.
DISPLAY_PLACES = 2

_INTERNAL_EXP = Decimal(1).scaleb(-INTERNAL_PLACES)
_DISPLAY_EXP = Decimal(1).scaleb(-DISPLAY_PLACES)


class CurrencyMismatchError(ValidationError):
    """Se ha intentado operar con dos monedas distintas sin convertir.

    Es la salvaguarda que el Milestone 39 no tenía: allí la regla existía en
    prosa y el código podía saltársela. Aquí no compila la operación.
    """


Scalar = int | Decimal


@dataclass(frozen=True)
class Money:
    """Un importe en una moneda. Inmutable, comparable, y sin conversiones
    implícitas de ninguna clase."""

    amount: Decimal
    #: Código ISO 4217, validado contra el catálogo de `trade_terms`.
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise ValidationError(
                f"Money needs a Decimal, got {type(self.amount).__name__}: "
                "a float would bring back the rounding error this type exists to remove. "
                "Use Money.of() or Money.from_legacy_float()"
            )
        if self.amount != self.amount:  # NaN
            raise ValidationError("Money cannot be NaN")
        if self.amount.is_infinite():
            raise ValidationError("Money cannot be infinite")
        currency_for(self.currency)
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "amount", self._quantize(self.amount, _INTERNAL_EXP))

    # ------------------------------------------------------------- construir

    @staticmethod
    def _quantize(value: Decimal, exponent: Decimal) -> Decimal:
        return value.quantize(exponent, rounding=ROUND_HALF_UP)

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> "Money":
        """Un importe a partir de texto, entero o `Decimal`.

        **No acepta `float` a propósito.** `Money.of(0.1, "EUR")` parece
        inofensivo y arrastra el error binario desde el primer carácter; quien
        venga de una columna `Float` usa `from_legacy_float`, que lo dice.
        """
        if isinstance(amount, float):
            raise ValidationError(
                "Money.of does not take a float: use Money.from_legacy_float(), "
                "which says out loud that the value crossed the legacy boundary"
            )
        try:
            return cls(amount=Decimal(amount), currency=currency)
        except InvalidOperation as exc:
            raise ValidationError(f"{amount!r} is not an amount") from exc

    @classmethod
    def from_legacy_float(cls, amount: float, currency: str) -> "Money":
        """La frontera de entrada desde las columnas `Float` que ya existían.

        Convierte **por su representación decimal** (`Decimal(str(x))`), no por
        la binaria: `Decimal(0.1)` es 0,1000000000000000055511151231257827…, y
        `Decimal(str(0.1))` es 0,1. La diferencia se acumula.
        """
        return cls(amount=Decimal(str(amount)), currency=currency)

    @classmethod
    def zero(cls, currency: str) -> "Money":
        """Cero **declarado**, que no es lo mismo que un coste desconocido.
        Quien lo use está afirmando que ese importe es cero."""
        return cls(amount=Decimal(0), currency=currency)

    # ------------------------------------------------------------ aritmética

    def _same_currency(self, other: "Money", operation: str) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot {operation} {self.currency} and {other.currency} without an explicit "
                "conversion: assuming they match invents an exchange rate of 1.00"
            )

    def __add__(self, other: "Money") -> "Money":
        self._same_currency(other, "add")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other, "subtract")
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Scalar) -> "Money":
        """Por un escalar. **Nunca por otro `Money`**: euros por euros no son
        euros, y el tipo no puede decir qué serían."""
        return Money(amount=self.amount * _scalar(factor), currency=self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Scalar) -> "Money":
        value = _scalar(divisor)
        if value == 0:
            raise ValidationError("cannot divide an amount by zero")
        return Money(amount=self.amount / value, currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    def ratio_to(self, other: "Money") -> Decimal:
        """Qué fracción es de otro importe **de la misma moneda**. Devuelve un
        `Decimal` sin moneda, porque un porcentaje no tiene moneda."""
        self._same_currency(other, "compare")
        if other.amount == 0:
            raise ValidationError("cannot express a ratio of an amount to zero")
        return self.amount / other.amount

    # ------------------------------------------------------------ comparar

    def __lt__(self, other: "Money") -> bool:
        self._same_currency(other, "compare")
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._same_currency(other, "compare")
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._same_currency(other, "compare")
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._same_currency(other, "compare")
        return self.amount >= other.amount

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    # ------------------------------------------------------------ presentar

    def rounded(self) -> "Money":
        """El importe a dos decimales, para enseñarlo. **Al final de todo**:
        redondear entre dos sumas mete el error que este tipo quita."""
        return Money(amount=self._quantize(self.amount, _DISPLAY_EXP), currency=self.currency)

    def __str__(self) -> str:
        return f"{self.rounded().amount} {self.currency}"


def _scalar(value: Scalar) -> Decimal:
    if isinstance(value, float):
        raise ValidationError(
            "a Money factor cannot be a float: convert it with Decimal(str(value)) "
            "so the legacy boundary is visible"
        )
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def total(amounts: list[Money], *, currency: str) -> Money:
    """La suma de varios importes, con la moneda dicha por quien llama.

    Se exige la moneda aunque la lista venga llena: una lista vacía tiene que
    poder sumar cero **en una moneda concreta**, y deducirla del primer elemento
    daría un resultado distinto según el orden.
    """
    result = Money.zero(currency)
    for amount in amounts:
        result = result + amount
    return result
