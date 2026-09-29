"""Qué cuesta vender en cada canal, sin contar nada dos veces (Milestone 40).

Economics consume la **taxonomía de canales del Milestone 38**. No hay una
segunda lista aquí: un canal que no esté declarado en `channels.py` falla, igual
que falla una señal con un canal inventado.

## La asimetría que justifica todo esto

En una web propia no hay comisión de marketplace —no es cero, es que no existe—
y sí hay coste de pasarela. En un marketplace hay comisión y la pasarela suele ir
dentro de ella. Calcular los dos canales con la misma plantilla daba un margen
equivocado en los dos sentidos a la vez.

## Los tres casos de doble contabilización, ya generalizados

El Milestone 39 detectó dos y aquí se convierten en instancias de un mecanismo
único (`CostStatus.INCLUDED_IN_ANOTHER`), con invariantes que fallan si el
contenedor no existe:

1. **Incoterm DDP**: los derechos de importación ya están en el precio del
   proveedor. El arancel está *dentro de `PRODUCT`*.
2. **Coste logístico de nuestro estimador**: `estimate_logistics_cost` multiplica
   por un factor de aduana, así que el arancel ya está *dentro de `LOGISTICS`*.
3. **Marketplace**: la pasarela de pago suele ir dentro de la comisión, así que
   está *dentro de `CHANNEL`*.

Ninguno de los tres vale cero euros y ninguno es desconocido: los tres están
pagados, contados una vez, en otro sitio.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import ValidationError
from app.economics.components import (
    CostBreakdown,
    CostConcept,
    included_in,
    known,
    not_applicable,
    unknown_optional,
    unknown_required,
)
from app.integrations.channels import ChannelKind, channel_for
from app.money.money import Money
from app.sourcing.provenance import SupplierFactProvenance
from app.sourcing.trade_terms import INCOTERMS


@dataclass(frozen=True)
class ChannelFee:
    """Lo que cobra un canal por vender. Con procedencia: hoy sale de fixtures
    y el margen que produce es un margen simulado."""

    #: Fracción del precio de venta.
    referral_fee_percent: Decimal
    fulfillment_fee_per_unit: Money
    provenance: SupplierFactProvenance
    source: str

    def total_for(self, sale_price: Money) -> Money:
        return sale_price * self.referral_fee_percent + self.fulfillment_fee_per_unit


@dataclass(frozen=True)
class QuoteCosts:
    """Lo que la cotización aporta al desglose, ya en la moneda del análisis."""

    product: Money | None
    product_provenance: SupplierFactProvenance
    product_source: str | None
    logistics: Money | None
    logistics_provenance: SupplierFactProvenance
    logistics_source: str | None
    incoterm: str | None
    #: Si el origen y el destino son el mismo mercado, no hay importación.
    same_market: bool = False


def _import_component(quote: QuoteCosts):
    """Dónde está el arancel: dentro del precio, dentro del transporte, fuera
    del escenario, o sin declarar."""
    incoterm = (quote.incoterm or "").strip().upper()
    term = INCOTERMS.get(incoterm)
    if term is not None and term.includes_import_duties:
        return included_in(
            CostConcept.IMPORT,
            CostConcept.PRODUCT,
            source=f"Incoterm {term.code}: el proveedor asume los derechos",
        )
    if quote.same_market:
        return not_applicable(
            CostConcept.IMPORT,
            "origen y destino son el mismo mercado: no hay importación",
        )
    if (
        quote.logistics is not None
        and quote.logistics_provenance is SupplierFactProvenance.AMAZONA_ESTIMATE
    ):
        # `estimate_logistics_cost` aplica un factor de aduana sobre el coste
        # declarado: el arancel ya viene dentro de esa cifra.
        return included_in(
            CostConcept.IMPORT,
            CostConcept.LOGISTICS,
            source="el estimador logístico ya aplica un factor de aduana",
        )
    return unknown_required(CostConcept.IMPORT)


def build_breakdown(
    *,
    channel_key: str,
    sale_price: Money,
    quote: QuoteCosts,
    channel_fee: ChannelFee | None = None,
    payment_cost: Money | None = None,
    payment_provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN,
    payment_source: str | None = None,
    other_variable_cost: Money | None = None,
    other_provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN,
    other_source: str | None = None,
) -> CostBreakdown:
    """Los seis componentes para un canal concreto.

    `channel_key` se valida contra el catálogo del Milestone 38. Un canal **no
    transaccional** —una superficie de búsqueda, una red social— se rechaza: ahí
    se descubre, no se cobra, y un margen de venta en un sitio donde no se vende
    no significa nada.
    """
    channel = channel_for(channel_key)
    if not channel.transactional:
        raise ValidationError(
            f"{channel.key} is not a transactional channel: nothing is sold there, so it "
            "has no unit economics. Use it for demand or competition signals instead"
        )

    components = []

    components.append(
        known(
            CostConcept.PRODUCT,
            quote.product,
            provenance=quote.product_provenance,
            source=quote.product_source,
        )
        if quote.product is not None
        else unknown_required(CostConcept.PRODUCT)
    )

    components.append(
        known(
            CostConcept.LOGISTICS,
            quote.logistics,
            provenance=quote.logistics_provenance,
            source=quote.logistics_source,
        )
        if quote.logistics is not None
        else unknown_required(CostConcept.LOGISTICS)
    )

    duties = _import_component(quote)
    if duties.included_in is CostConcept.PRODUCT and quote.product is None:
        # Los derechos están dentro de un precio que nadie ha declarado, así que
        # tampoco están contados: el arancel es desconocido, no «ya pagado».
        duties = unknown_required(CostConcept.IMPORT)
    elif duties.included_in is CostConcept.LOGISTICS and quote.logistics is None:
        duties = unknown_required(CostConcept.IMPORT)
    components.append(duties)

    # --- canal -------------------------------------------------------------
    channel_known = False
    if channel.kind is ChannelKind.OWN_WEB:
        components.append(
            not_applicable(
                CostConcept.CHANNEL,
                "una web propia no paga comisión de marketplace: no hay intermediario que cobre",
            )
        )
    elif channel_fee is None:
        components.append(unknown_required(CostConcept.CHANNEL))
    else:
        components.append(
            known(
                CostConcept.CHANNEL,
                channel_fee.total_for(sale_price),
                provenance=channel_fee.provenance,
                source=channel_fee.source,
            )
        )
        channel_known = True

    # --- pago --------------------------------------------------------------
    if payment_cost is not None:
        components.append(
            known(
                CostConcept.PAYMENT,
                payment_cost,
                provenance=payment_provenance,
                source=payment_source,
            )
        )
    elif channel.kind is ChannelKind.MARKETPLACE and channel_known:
        # En un marketplace la pasarela va dentro de la comisión. Solo se puede
        # declarar así cuando la comisión se conoce: estar dentro de algo que
        # nadie ha declarado no cuenta nada, y el invariante lo rechaza.
        components.append(
            included_in(
                CostConcept.PAYMENT,
                CostConcept.CHANNEL,
                source="el marketplace cobra el pago dentro de su comisión",
            )
        )
    elif channel.kind is ChannelKind.OWN_WEB:
        # En una web propia la pasarela la pagamos nosotros y cambia el margen:
        # no declararla no es un detalle.
        components.append(unknown_required(CostConcept.PAYMENT))
    else:
        components.append(unknown_optional(CostConcept.PAYMENT))

    # --- otros variables ---------------------------------------------------
    components.append(
        known(
            CostConcept.OTHER_VARIABLE,
            other_variable_cost,
            provenance=other_provenance,
            source=other_source,
        )
        if other_variable_cost is not None
        else unknown_optional(CostConcept.OTHER_VARIABLE)
    )

    return CostBreakdown(components=tuple(components))
