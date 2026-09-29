"""De qué está hecho un margen, componente a componente (Milestone 40, ADR 0018).

Un margen es una resta, y una resta esconde de dónde salió cada sumando. Este
módulo impide esconderlo: cada coste dice **cuánto**, **quién lo sostiene** y
—lo que importa de verdad— **en cuál de cinco situaciones está**.

## Por qué cinco estados y no un número que puede faltar

Porque «no resto nada» significa cuatro cosas distintas y un `None` las aplana:

- La comisión de marketplace en una web propia **no existe**. No es cero: es que
  la pregunta no aplica.
- El arancel de una cotización DDP **ya está dentro** del precio del proveedor.
  Restarlo otra vez lo cuenta dos veces; ponerlo a cero dice que no hay arancel.
- El coste de la pasarela de pago en una web propia **nadie lo ha dicho**, y
  cambia el resultado. No se puede seguir.
- Un coste variable menor que nadie ha declarado **no cambia la respuesta**. Se
  anota y se sigue.

Las cuatro suman cero euros y las cuatro son afirmaciones diferentes. La quinta
situación es la normal: el coste se conoce.

## La protección contra contar dos veces

En el Milestone 39 se detectaron dos casos concretos —el estimador logístico que
ya lleva aranceles dentro, y la comisión de canal que un agente restaba por su
cuenta—. Aquí dejan de ser parches: un componente que está dentro de otro **lo
nombra**, y hay invariantes que fallan si ese otro no existe, si un componente
está dentro de dos, o si dos se contienen en círculo.

La suma recorre **solo** los componentes conocidos. Esa es toda la aritmética, y
por eso no hay forma de sumar algo dos veces sin que un invariante lo vea.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import ValidationError
from app.money.money import Money, total
from app.sourcing.provenance import STORABLE, SupplierFactProvenance


class CostConcept(StrEnum):
    """Los componentes de la economía unitaria del plan maestro.

    Cerrado: un concepto nuevo aquí es una decisión sobre qué compone un margen,
    no una clave más en un diccionario.
    """

    #: Lo que cuesta la mercancía: el precio del proveedor.
    PRODUCT = "product"
    #: Transporte hasta el mercado de destino.
    LOGISTICS = "logistics"
    #: Aranceles y despacho de importación.
    IMPORT = "import"
    #: Comisión y tarifas del canal donde se vende.
    CHANNEL = "channel"
    #: Pasarela de pago y coste de transacción.
    PAYMENT = "payment"
    #: Lo demás que varíe con cada unidad y se conozca.
    OTHER_VARIABLE = "other_variable"


class CostStatus(StrEnum):
    """En qué situación está un componente. Cinco, y ninguna es «cero»."""

    #: Hay importe y hay quién lo sostiene. Es el único que entra en la suma.
    KNOWN = "known"
    #: Ya está contado dentro de otro componente, **y dice cuál**. No se suma:
    #: sumarlo sería contarlo dos veces. Tampoco es cero — existe y está pagado.
    INCLUDED_IN_ANOTHER = "included_in_another"
    #: No existe en este escenario, con el motivo escrito. Una comisión de
    #: marketplace en una web propia.
    NOT_APPLICABLE = "not_applicable"
    #: Nadie lo ha dicho **y cambia la respuesta**. Hace el cálculo no evaluable.
    UNKNOWN_REQUIRED = "unknown_required"
    #: Nadie lo ha dicho y no cambia la respuesta de forma material. Se anota.
    UNKNOWN_OPTIONAL = "unknown_optional"


@dataclass(frozen=True)
class CostComponent:
    """Un componente del margen, con su situación y su procedencia."""

    concept: CostConcept
    status: CostStatus
    #: Solo cuando `KNOWN`. En cualquier otra situación tiene que ser `None`:
    #: un importe junto a «no aplica» es una contradicción guardada.
    amount: Money | None = None
    #: Quién sostiene **este** importe. Va aquí y no solo en el resultado: un
    #: margen no vale más que el más flojo de sus sumandos, y para saber cuál es
    #: el más flojo hay que preguntárselo a cada uno.
    provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    #: De dónde salió: `manual:<usuario>`, `app/sourcing/logistics.py`, el mock.
    source: str | None = None
    #: Solo cuando `INCLUDED_IN_ANOTHER`: dentro de cuál está.
    included_in: CostConcept | None = None
    #: Solo cuando `NOT_APPLICABLE`: por qué no aplica, en una frase.
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is CostStatus.KNOWN:
            if self.amount is None:
                raise ValidationError(
                    f"{self.concept} is marked known without an amount: "
                    "if nobody said how much, it is unknown, not known"
                )
            if self.provenance not in STORABLE:
                raise ValidationError(
                    f"{self.concept} has an amount and no provenance: "
                    "an unattributed cost is what Milestone 39 removed from suppliers"
                )
        elif self.amount is not None:
            raise ValidationError(
                f"{self.concept} is {self.status} and still carries an amount: "
                "a cost that is not known cannot have a figure attached"
            )

        if self.status is CostStatus.INCLUDED_IN_ANOTHER:
            if self.included_in is None:
                raise ValidationError(
                    f"{self.concept} says it is included in another cost without naming it: "
                    "an unnamed container is how a cost gets counted twice"
                )
            if self.included_in is self.concept:
                raise ValidationError(f"{self.concept} cannot be included in itself")
        elif self.included_in is not None:
            raise ValidationError(
                f"{self.concept} names a container but is {self.status}"
            )

        if self.status is CostStatus.NOT_APPLICABLE and not (self.reason or "").strip():
            raise ValidationError(
                f"{self.concept} is marked not applicable without saying why: "
                "'does not apply' is a claim about the scenario, not an absence"
            )

    @property
    def counts(self) -> bool:
        """Si entra en la suma. **Solo lo conocido.**"""
        return self.status is CostStatus.KNOWN

    @property
    def blocks_evaluation(self) -> bool:
        return self.status is CostStatus.UNKNOWN_REQUIRED


def known(
    concept: CostConcept,
    amount: Money,
    *,
    provenance: SupplierFactProvenance,
    source: str | None = None,
) -> CostComponent:
    return CostComponent(
        concept=concept,
        status=CostStatus.KNOWN,
        amount=amount,
        provenance=provenance,
        source=source,
    )


def included_in(concept: CostConcept, container: CostConcept, *, source: str | None = None) -> CostComponent:
    return CostComponent(
        concept=concept,
        status=CostStatus.INCLUDED_IN_ANOTHER,
        included_in=container,
        source=source,
    )


def not_applicable(concept: CostConcept, reason: str) -> CostComponent:
    return CostComponent(concept=concept, status=CostStatus.NOT_APPLICABLE, reason=reason)


def unknown_required(concept: CostConcept) -> CostComponent:
    return CostComponent(concept=concept, status=CostStatus.UNKNOWN_REQUIRED)


def unknown_optional(concept: CostConcept) -> CostComponent:
    return CostComponent(concept=concept, status=CostStatus.UNKNOWN_OPTIONAL)


class DoubleCountingError(ValidationError):
    """Un componente se contaría dos veces, o dice estar dentro de algo que no
    puede contenerlo.

    Falla al construir el desglose. Es el error más caro de este dominio porque
    **no se nota**: un margen con el arancel contado dos veces sigue pareciendo
    un margen.
    """


def check_invariants(components: list[CostComponent]) -> None:
    """Las cuatro reglas que impiden contar un coste dos veces.

    1. Cada concepto aparece **exactamente una vez**.
    2. Lo que dice estar dentro de otro nombra un contenedor que **existe y se
       conoce**. Estar dentro de algo que nadie ha declarado no cuenta nada.
    3. La suma recorre solo lo conocido — garantizado por `counts`, y aquí se
       comprueba que no haya conocidos duplicados que lo rompan.

    No hace falta una regla contra los ciclos: un ciclo exige que todos sus
    miembros estén `INCLUDED_IN_ANOTHER`, y entonces ninguno es `KNOWN`, así que
    la regla 2 lo rechaza antes. Escribirla además sería código que no se puede
    alcanzar.
    """
    by_concept: dict[CostConcept, CostComponent] = {}
    for component in components:
        if component.concept in by_concept:
            raise DoubleCountingError(
                f"{component.concept} appears twice in the breakdown: "
                "one of the two would be added to the total a second time"
            )
        by_concept[component.concept] = component

    missing = [c for c in CostConcept if c not in by_concept]
    if missing:
        raise ValidationError(
            "a breakdown must state every cost concept, including the ones that do not "
            f"apply: missing {', '.join(c.value for c in missing)}. A concept left out is "
            "indistinguishable from one nobody thought about"
        )

    for component in components:
        if component.included_in is None:
            continue
        container = by_concept[component.included_in]
        if not container.counts:
            raise DoubleCountingError(
                f"{component.concept} says it is included in {component.included_in}, "
                f"which is {container.status}: being inside something nobody declared "
                "means nothing was counted at all"
            )


@dataclass(frozen=True)
class CostBreakdown:
    """Los seis componentes de un margen, con sus situaciones."""

    components: tuple[CostComponent, ...]

    def __post_init__(self) -> None:
        check_invariants(list(self.components))

    def of(self, concept: CostConcept) -> CostComponent:
        for component in self.components:
            if component.concept is concept:
                return component
        raise KeyError(concept)

    @property
    def counted(self) -> tuple[CostComponent, ...]:
        return tuple(c for c in self.components if c.counts)

    @property
    def blocking(self) -> tuple[CostConcept, ...]:
        """Los costes obligatorios que nadie ha declarado. Mientras esta lista
        no esté vacía, el margen no es evaluable."""
        return tuple(c.concept for c in self.components if c.blocks_evaluation)

    @property
    def omitted(self) -> tuple[CostConcept, ...]:
        """Los opcionales que faltan. No impiden el cálculo y el resultado los
        nombra: un margen al que le falta un coste menor sigue siendo optimista
        en esa cantidad."""
        return tuple(
            c.concept for c in self.components if c.status is CostStatus.UNKNOWN_OPTIONAL
        )

    def total_cost(self, *, currency: str) -> Money:
        """La suma de lo conocido, y de nada más."""
        return total([c.amount for c in self.counted if c.amount is not None], currency=currency)

    @property
    def weakest_provenance(self) -> SupplierFactProvenance:
        """La procedencia más floja de los componentes que se suman.

        **No es una puntuación**: es un suelo. Un margen no vale más que el más
        flojo de sus sumandos, así que si uno solo viene de un fixture, el
        margen es un margen simulado y tiene que decirlo — la misma regla que
        hace simulado a un proveedor compuesto en la ADR 0008.
        """
        from app.sourcing.provenance import rank

        counted = self.counted
        if not counted:
            return SupplierFactProvenance.UNKNOWN
        return max((c.provenance for c in counted), key=rank)
