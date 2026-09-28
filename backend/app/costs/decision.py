"""¿Cabe esta llamada? (Milestone 37, plan §25)

Función pura, como `evaluate_action` del ActionGate y `assess_pipeline_run` del
pipeline: entran la política del proveedor, lo que el propietario ha autorizado y
lo que ya se ha consumido; sale una decisión con su motivo. Nada de base de
datos, nada de red, nada de reloj.

## El orden de las comprobaciones importa

Se comprueba primero la autorización de gasto y después las cuotas, porque son
denegaciones de naturaleza distinta y quien lea el motivo necesita la más
importante: «no hay presupuesto autorizado» se arregla con una decisión del
propietario, y «se agotó la cuota diaria» se arregla esperando a mañana.

## Denegar no es fallar

Una denegación no es una avería: es el sistema haciendo su trabajo. Quien la
recibe **no produce señal** para ese término, y una señal ausente se queda
ausente (ADR 0012 §4). Nunca un cero.
"""

from dataclasses import dataclass

from app.costs.policy import CostPolicy, Pricing, SpendLimit


@dataclass(frozen=True)
class Usage:
    """Lo ya consumido con ese proveedor, en las ventanas que importan."""

    units_this_run: int = 0
    units_today: int = 0
    cost_today: float = 0.0
    cost_this_run: float = 0.0


@dataclass(frozen=True)
class CostDecision:
    allowed: bool
    #: Qué se va a gastar si se permite. Estimado, porque el coste real solo lo
    #: sabe el proveedor y a veces lo dice más tarde.
    estimated_cost: float
    currency: str
    #: Por qué no, cuando no. `None` cuando sí: un motivo de permiso no aporta.
    reason: str | None = None


def evaluate_api_call(
    *,
    policy: CostPolicy,
    limit: SpendLimit | None,
    units: int,
    usage: Usage,
) -> CostDecision:
    """Si se puede hacer la llamada, y lo que costaría."""
    estimated = round(policy.cost_per_unit * units, 6)
    currency = limit.currency if limit is not None else policy.currency

    def deny(reason: str) -> CostDecision:
        return CostDecision(
            allowed=False, estimated_cost=estimated, currency=currency, reason=reason
        )

    # 1. Gasto sin autorizar. El presupuesto no se hereda de ninguna parte.
    if policy.pricing is Pricing.PAID and limit is None:
        return deny(
            f"{policy.provider} cobra por uso y no tiene límite de gasto autorizado; "
            "sin autorización no se llama"
        )

    # 2. Monedas que no coinciden. Sumar euros con dólares es peor que no sumar.
    if limit is not None and limit.currency != policy.currency:
        return deny(
            f"el límite de {policy.provider} está en {limit.currency} y su precio en "
            f"{policy.currency}; no se convierte una moneda por nuestra cuenta"
        )

    # 3. Nuestro propio tope por ejecución, para no agotar el arriendo del trabajo.
    if policy.max_units_per_run is not None:
        if usage.units_this_run + units > policy.max_units_per_run:
            return deny(
                f"{usage.units_this_run + units} {policy.unit} en esta ejecución supera el tope "
                f"de {policy.max_units_per_run} de {policy.provider}"
            )

    # 4. La cuota que publica el proveedor, y la que el propietario haya acotado.
    daily_unit_caps = [
        cap
        for cap in (policy.quota_units_per_day, limit.max_units_per_day if limit else None)
        if cap is not None
    ]
    for cap in daily_unit_caps:
        if usage.units_today + units > cap:
            return deny(
                f"{usage.units_today + units} {policy.unit} hoy supera la cuota de {cap} "
                f"de {policy.provider}"
            )

    # 5. El dinero, cuando hay dinero de por medio.
    if limit is not None and estimated > 0:
        if limit.max_cost_per_run is not None and usage.cost_this_run + estimated > limit.max_cost_per_run:
            return deny(
                f"{round(usage.cost_this_run + estimated, 6)} {currency} en esta ejecución supera "
                f"el límite autorizado de {limit.max_cost_per_run}"
            )
        if limit.max_cost_per_day is not None and usage.cost_today + estimated > limit.max_cost_per_day:
            return deny(
                f"{round(usage.cost_today + estimated, 6)} {currency} hoy supera el límite "
                f"autorizado de {limit.max_cost_per_day} por día"
            )

    return CostDecision(allowed=True, estimated_cost=estimated, currency=currency)
