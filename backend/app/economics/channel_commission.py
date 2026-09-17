def compute_channel_net_margin(
    *,
    sale_price: float | None,
    unit_landed_cost: float | None,
    referral_fee_percent: float,
    fulfillment_fee_per_unit: float,
) -> float | None:
    """Net margin per unit after a sales channel's commission — referral
    fee (percent of sale price) plus a flat fulfillment fee. Single
    source of truth for channel commission math (AMAZONA_cambio_
    arquitectura_eliminacion_modulo_mercado.md: "comisiones/margen por
    canal -> Economía y rentabilidad"), called by any channel agent
    that needs it instead of inlining the arithmetic."""
    if sale_price is None or unit_landed_cost is None:
        return None
    referral_fee = sale_price * referral_fee_percent
    return sale_price - unit_landed_cost - referral_fee - fulfillment_fee_per_unit
