"""Lo que llevamos gastado y lo que queda de cuota (Milestone 37, plan §25).

Una ruta de lectura y nada más: aquí no se autoriza gasto ni se cambian límites.
Los límites viven en configuración porque son dinero del propietario y no una
preferencia de la aplicación; el día que se editen desde el panel tendrán su
propia ruta mutadora, con su acción y su rol.

Categoría de lectura: **diagnóstico**, la misma que `/health/detailed`. Lo que se
publica aquí es cuánta cuota consume este despliegue, no información de negocio:
la misma familia que «qué proveedor responde en cada dominio», que ya vive ahí.
"""

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.costs.policy import POLICIES, policy_for
from app.db.models.external_api_cost import ExternalApiCost
from app.db.session import get_db
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/costs", tags=["costs"])


class ProviderUsageOut(BaseModel):
    """Lo consumido hoy con un proveedor, y contra qué se compara."""

    provider: str
    #: `free` o `paid`. No es lo mismo «no cuesta» que «no tiene límite».
    pricing: str
    #: Qué se cuenta: peticiones, tokens, créditos.
    unit: str
    units_today: int
    #: Cuántas llamadas se denegaron hoy, y por qué la última. Sin esto, una
    #: investigación sin señales parecería una avería.
    denied_today: int
    last_denied_reason: str | None
    estimated_cost_today: float
    #: Lo que el proveedor ha cobrado de verdad, cuando lo dice. **Nulo no es
    #: cero**: es que todavía no lo ha dicho.
    actual_cost_today: float | None
    currency: str
    #: La cuota que publica el proveedor, si publica alguna. `None` = no hay.
    quota_units_per_day: int | None
    #: Nuestro tope por ejecución, por el arriendo de 60 s del runtime.
    max_units_per_run: int | None
    #: Lo que el propietario ha autorizado gastar. `None` en todos los campos
    #: significa que no hay autorización — y sin autorización un proveedor de pago
    #: no se llama.
    authorised_cost_per_day: float | None
    authorised_cost_per_run: float | None
    #: Dónde se comprobaron el precio y la cuota.
    source: str


@router.get("/api-usage", response_model=list[ProviderUsageOut])
def list_api_usage(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _: None = Depends(authorize(ApiAction.DIAGNOSTICS_READ)),
) -> list[ProviderUsageOut]:
    """Un renglón por proveedor con política declarada.

    Se listan **todos** los proveedores conocidos, también los que hoy no se han
    usado: un proveedor ausente de la lista se confundiría con uno sin política, y
    un cero en `units_today` de un proveedor que sí existe es un cero medido, no
    inventado.
    """
    start = datetime.datetime.combine(
        datetime.datetime.now(datetime.UTC).date(), datetime.time.min, tzinfo=datetime.UTC
    )
    limits = settings.spend_limits

    rows = db.execute(
        select(
            ExternalApiCost.provider,
            ExternalApiCost.outcome,
            func.count(ExternalApiCost.id),
            func.coalesce(func.sum(ExternalApiCost.units), 0),
            func.coalesce(func.sum(ExternalApiCost.estimated_cost), 0.0),
            func.sum(ExternalApiCost.actual_cost),
        )
        .where(ExternalApiCost.observed_at >= start)
        .group_by(ExternalApiCost.provider, ExternalApiCost.outcome)
    ).all()

    allowed = {row[0]: row for row in rows if row[1] == "allowed"}
    denied = {row[0]: row for row in rows if row[1] == "denied"}

    out: list[ProviderUsageOut] = []
    for provider in sorted(POLICIES):
        policy = policy_for(provider)
        limit = limits.get(provider)
        used = allowed.get(provider)
        refused = denied.get(provider)
        out.append(
            ProviderUsageOut(
                provider=provider,
                pricing=policy.pricing.value,
                unit=policy.unit,
                units_today=int(used[3]) if used else 0,
                denied_today=int(refused[2]) if refused else 0,
                last_denied_reason=_last_denied_reason(db, provider, start),
                estimated_cost_today=round(float(used[4]), 6) if used else 0.0,
                # Nulo se conserva: la suma de nada no es cero euros cobrados.
                actual_cost_today=float(used[5]) if used and used[5] is not None else None,
                currency=limit.currency if limit else policy.currency,
                quota_units_per_day=policy.quota_units_per_day,
                max_units_per_run=policy.max_units_per_run,
                authorised_cost_per_day=limit.max_cost_per_day if limit else None,
                authorised_cost_per_run=limit.max_cost_per_run if limit else None,
                source=policy.source,
            )
        )
    return out


def _last_denied_reason(db: Session, provider: str, start: datetime.datetime) -> str | None:
    return db.execute(
        select(ExternalApiCost.denied_reason)
        .where(
            ExternalApiCost.provider == provider,
            ExternalApiCost.outcome == "denied",
            ExternalApiCost.observed_at >= start,
        )
        .order_by(ExternalApiCost.observed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
