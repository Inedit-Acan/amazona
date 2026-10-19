"""El presupuesto operativo, para verlo (M47). Una ruta de lectura y nada más.

Aquí no se autoriza, no se reserva, no se compromete ni se libera nada: el techo lo autoriza el propietario
(`python -m app.cli authorise-budget`) y el saldo lo mueven el orquestador y las aprobaciones, siempre a través de
`BudgetLedgerService`. Esta ruta solo cuenta lo que hay, con las cifras tal como están en las filas.

Dos respuestas distintas, a propósito:

- **No hay presupuesto autorizado** → `200` con `authorised = false` y `budget = null`. Es un hecho (el propietario no
  ha autorizado ninguno), no un fallo; y no se inventa uno.
- **Lo que no se pudo leer** → el error de siempre (4xx/5xx). Quien lee distingue «no hay» de «no sé».

Los importes salen como texto decimal exacto («1.00»), igual que los ingresos (ADR 0030): nadie los convierte a `float`.
"""

import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.budgets.service import BudgetLedgerService, BudgetSummary
from app.db.session import get_db

router = APIRouter(prefix="/api/budget", tags=["budget"])


class BudgetOut(BaseModel):
    #: El ámbito del presupuesto (hay uno por nombre).
    name: str
    #: El periodo que declara la fila (`monthly`). Es una etiqueta: el sistema no reinicia el saldo al cambiar de
    #: periodo.
    period: str
    #: La moneda en la que se autoriza el techo. No es una columna de `budgets`: es la moneda contable del contrato
    #: (`ACCOUNTING_CURRENCY`), la misma que lleva la auditoría de la autorización. `currency_source` lo dice.
    currency: str
    currency_source: Literal["accounting_currency"]
    hard_limit: str
    soft_limit: str | None
    reserved: str
    committed: str
    spent: str
    #: `hard_limit − reserved − committed`: lo que el motor llama disponible. Puede ser negativo solo si el saldo está
    #: desajustado, y entonces se ve (no se recorta a cero).
    remaining: str


class BudgetReadOut(BaseModel):
    authorised: bool
    budget: BudgetOut | None
    #: El instante, en UTC, en que el servidor leyó las filas.
    read_at: datetime.datetime


def _out(summary: BudgetSummary) -> BudgetOut:
    return BudgetOut(
        name=summary.name,
        period=summary.period,
        currency=summary.currency,
        currency_source="accounting_currency",
        hard_limit=str(summary.hard_limit),
        soft_limit=str(summary.soft_limit) if summary.soft_limit is not None else None,
        reserved=str(summary.reserved),
        committed=str(summary.committed),
        spent=str(summary.spent),
        remaining=str(summary.remaining),
    )


@router.get("", response_model=BudgetReadOut)
def read_budget(db: Session = Depends(get_db)) -> BudgetReadOut:
    summary = BudgetLedgerService(db).summary()
    return BudgetReadOut(
        authorised=summary is not None,
        budget=_out(summary) if summary is not None else None,
        read_at=datetime.datetime.now(datetime.UTC),
    )
