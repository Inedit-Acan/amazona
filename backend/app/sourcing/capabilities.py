"""Qué sabe hacer un proveedor, y quién lo dice (Milestone 39, ADR 0017).

El plan maestro §16 es un principio del proyecto, no una funcionalidad: vender
primero, cobrar, comprar al proveedor y que el proveedor envíe. Y dice, en la
misma página, «no asumir que esto siempre es legal/logísticamente viable»: cada
proveedor **declara** si soporta envío directo, dropshipping, envío ciego,
embalaje propio, tracking, devoluciones, dirección de retorno en la UE y SLA.

Hasta este milestone ninguna de las ocho existía en el backend. La pantalla de
Proveedores las enseñaba desde `lib/demo/sourcing.ts`, inventadas con un
generador determinista por proveedor: ocho afirmaciones sobre el mundo salidas
de una semilla.

## Por qué no son booleanos

Porque «este proveedor hace dropshipping» es una afirmación con autor. Dicha por
el comercial del proveedor vale una cosa; comprobada contra un contrato firmado,
otra; deducida por nosotros de que su MOQ es 1, otra distinta. Un `bool` las
aplana todas y además confunde «dice que no» con «no lo ha dicho», que es el
mismo error que el cero inventado.

Por eso una capacidad se declara con `CapabilityDeclaration`: soportada o no,
**con** procedencia, fuente, fecha y una nota. Y la ausencia de declaración se
responde `UNKNOWN`, no `False`.

## El alcance

Una declaración puede ser del proveedor entero o **de un producto concreto**,
porque §16 dice «cada proveedor/producto debe declarar». Un fabricante puede
enviar directo un artículo pequeño y no uno voluminoso, y una capacidad por
proveedor no podría representarlo. `product_id` nulo significa «para todo lo
suyo»; una declaración con producto gana sobre la general para ese producto.
"""

import datetime
from dataclasses import dataclass
from enum import StrEnum

from app.core.errors import ValidationError
from app.sourcing.provenance import STORABLE, SupplierFactProvenance


class SupplyCapability(StrEnum):
    """Las ocho del plan maestro §16. Conjunto **cerrado**: añadir una es una
    decisión de producto con su migración, no una clave nueva en un diccionario.

    Cerrado por el mismo motivo que los cuatro tipos de canal del Milestone 38:
    una capacidad escrita con un typo sería una capacidad fantasma que nadie
    consulta, y el sistema respondería «no declarada» sobre algo declarado.
    """

    #: El proveedor envía al cliente final en lugar de a nosotros.
    DIRECT_SHIPPING = "direct_shipping"
    #: Acepta pedidos unitarios disparados por una venta ya cobrada, que es el
    #: modelo de §16. Es más que `DIRECT_SHIPPING`: incluye no exigir volumen.
    DROPSHIPPING = "dropshipping"
    #: Envía sin que el paquete revele quién fabricó ni de dónde viene.
    BLIND_SHIPPING = "blind_shipping"
    #: Admite embalaje o marca nuestros.
    CUSTOM_PACKAGING = "custom_packaging"
    #: Da número de seguimiento utilizable por el cliente final.
    TRACKING = "tracking"
    #: Acepta devoluciones.
    RETURNS = "returns"
    #: Tiene dirección de retorno **en la UE**. Separada de `RETURNS` a
    #: propósito: aceptar devoluciones a una dirección en Shenzhen no es lo
    #: mismo para un comprador europeo, y el derecho de desistimiento no se
    #: cumple igual.
    EU_RETURN_ADDRESS = "eu_return_address"
    #: Compromiso de servicio por contrato, no una promesa comercial.
    SLA = "sla"


#: Qué capacidades tiene que tener declaradas un proveedor para que el modelo
#: sin stock propio de §16 sea afirmable con él. No es un filtro automático:
#: es lo que hay que **preguntarle**, y lo que la pantalla enseña como hueco
#: mientras no se sepa.
MODEL_CRITICAL = (
    SupplyCapability.DIRECT_SHIPPING,
    SupplyCapability.DROPSHIPPING,
    SupplyCapability.BLIND_SHIPPING,
    SupplyCapability.TRACKING,
    SupplyCapability.EU_RETURN_ADDRESS,
)


@dataclass(frozen=True)
class CapabilityDeclaration:
    """Una capacidad declarada: qué, si la soporta, quién lo dice y desde cuándo."""

    capability: SupplyCapability
    supported: bool
    provenance: SupplierFactProvenance
    #: De dónde salió. Obligatorio para `THIRD_PARTY_VERIFIED`; recomendable
    #: siempre, porque «lo dijo el proveedor» sin decir dónde no se puede
    #: releer dentro de seis meses.
    source: str | None = None
    #: Lo que no cabe en un booleano: «solo para pedidos de más de 20», «con
    #: recargo de 0,80 €». Se guarda y **no se interpreta**.
    note: str | None = None
    #: Cuándo se supo. Una capacidad declarada hace dos años y una de ayer no
    #: valen lo mismo, y la diferencia solo es visible si consta la fecha.
    observed_at: datetime.datetime | None = None
    #: `None` = vale para todo lo del proveedor. Con producto, solo para él.
    product_id: str | None = None

    def __post_init__(self) -> None:
        if self.provenance not in STORABLE:
            raise ValidationError(
                f"a capability cannot be declared {self.provenance}: "
                "not declaring it already says that, and a row saying 'unknown' "
                "is indistinguishable from a failed import"
            )
        if self.provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (
            self.source or ""
        ).strip():
            from app.sourcing.provenance import MissingVerifierError

            raise MissingVerifierError(
                f"{self.capability} cannot be third-party verified without naming "
                "the verifier (plan maestro §10)"
            )


@dataclass(frozen=True)
class CapabilityAnswer:
    """Lo que se sabe de **una** capacidad para un proveedor y, si se pregunta
    por uno, un producto. Es lo que la API y la pantalla consumen."""

    capability: SupplyCapability
    #: `None` significa que nadie lo ha declarado. **No significa «no»**.
    supported: bool | None
    provenance: SupplierFactProvenance
    source: str | None = None
    note: str | None = None
    observed_at: datetime.datetime | None = None
    #: Si la respuesta viene de una declaración específica de ese producto.
    product_specific: bool = False

    @property
    def known(self) -> bool:
        return self.supported is not None


def _applies(declaration: CapabilityDeclaration, product_id: str | None) -> bool:
    if declaration.product_id is None:
        return True
    return declaration.product_id == product_id


def resolve(
    declarations: list[CapabilityDeclaration],
    capability: SupplyCapability,
    *,
    product_id: str | None = None,
) -> CapabilityAnswer:
    """Qué se sabe de una capacidad, según lo declarado.

    Manda lo específico del producto sobre lo general del proveedor: quien se
    molesta en decir algo de **este** artículo está corrigiendo la regla de la
    casa, no repitiéndola. Dentro del mismo alcance manda la procedencia que más
    pesa, y entre iguales la declaración más reciente — con una fecha ausente
    considerada la más antigua, porque no consta que sea de ayer.
    """
    candidates = [
        d for d in declarations if d.capability is capability and _applies(d, product_id)
    ]
    if not candidates:
        return CapabilityAnswer(
            capability=capability,
            supported=None,
            provenance=SupplierFactProvenance.UNKNOWN,
        )

    epoch = datetime.datetime.min.replace(tzinfo=datetime.UTC)

    def preference(d: CapabilityDeclaration) -> tuple[int, int, float]:
        from app.sourcing.provenance import rank

        specific = 0 if d.product_id is not None else 1
        when = (d.observed_at or epoch).timestamp()
        return (specific, rank(d.provenance), -when)

    chosen = min(candidates, key=preference)
    return CapabilityAnswer(
        capability=chosen.capability,
        supported=chosen.supported,
        provenance=chosen.provenance,
        source=chosen.source,
        note=chosen.note,
        observed_at=chosen.observed_at,
        product_specific=chosen.product_id is not None,
    )


def profile(
    declarations: list[CapabilityDeclaration], *, product_id: str | None = None
) -> list[CapabilityAnswer]:
    """Las ocho capacidades, declaradas o no, siempre en el mismo orden.

    Devuelve las ocho **a propósito**, incluidas las que nadie ha declarado: una
    lista que solo trae lo conocido deja al que la lee sin saber si faltan
    porque no se soportan o porque no se ha preguntado, y ese es justo el error
    que este módulo quita de en medio.
    """
    return [resolve(declarations, capability, product_id=product_id) for capability in SupplyCapability]


def unanswered(
    declarations: list[CapabilityDeclaration], *, product_id: str | None = None
) -> list[SupplyCapability]:
    """Las capacidades críticas para el modelo §16 que siguen sin respuesta.

    Es la lista de lo que hay que preguntarle al proveedor antes de afirmar que
    se le puede vender sin stock. Vacía no quiere decir «compatible»: quiere
    decir que ya no faltan respuestas.
    """
    return [
        capability
        for capability in MODEL_CRITICAL
        if not resolve(declarations, capability, product_id=product_id).known
    ]
