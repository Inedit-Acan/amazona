"""Pedidos (Milestone 44, ADR 0028).

Aquí un pedido se crea y se lee. **No hay ninguna ruta que lo marque como pagado**: eso lo decide un evento de
pago verificado (`PaymentService`) y nada más. Las lecturas no escriben.
"""

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.db.models.order import Order as OrderModel
from app.db.models.order import OrderItem as OrderItemModel
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.money.money import Money
from app.money.serialization import money_to_json
from app.orders.attention import attention_reasons
from app.orders.domain import OrderStatus
from app.orders.service import NewOrderLine, OrderService
from app.permissions.policies import ApiAction

router = APIRouter(prefix="/api/orders", tags=["orders"])

_AMOUNT = r"^\d{1,14}(\.\d{1,4})?$"


class MoneyIn(BaseModel):
    """Un importe como cadena y moneda: un número JSON sería un `float` y traería su error binario."""

    model_config = ConfigDict(extra="forbid")

    amount: str = Field(pattern=_AMOUNT)
    currency: str = Field(min_length=3, max_length=3)

    def to_money(self) -> Money:
        return Money.of(self.amount, self.currency)


class OrderLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    quantity: int = Field(ge=1)
    unit_price: MoneyIn
    supplier_quote_id: str | None = None
    declared_unit_cost: MoneyIn | None = None


class OrderCreate(BaseModel):
    """Lo que se necesita para crear un pedido. Ni un solo dato personal: `customer_ref` es opaca."""

    model_config = ConfigDict(extra="forbid")

    customer_ref: str = Field(min_length=1, max_length=64)
    market: str = Field(min_length=1, max_length=16)
    lines: list[OrderLineCreate] = Field(min_length=1)

    @field_validator("customer_ref")
    @classmethod
    def _no_whitespace(cls, value: str) -> str:
        return value.strip()


class MoneyOut(BaseModel):
    amount: str
    currency: str


class OrderItemOut(BaseModel):
    id: str
    line_number: int
    product_id: str
    supplier_id: str | None
    supplier_quote_id: str | None
    quantity: int
    allocated_quantity: int
    unit_price: MoneyOut
    line_total: MoneyOut
    unit_cost: MoneyOut | None
    cost_provenance: str | None
    cost_source: str | None


class OrderOut(BaseModel):
    id: str
    customer_ref: str
    market: str
    status: str
    is_simulated: bool
    amount_due: MoneyOut
    items: list[OrderItemOut]
    created_at: datetime.datetime
    paid_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None
    correlation_id: str
    #: Se calcula al leer, nunca se guarda. Vacío = nada que mirar.
    attention_required: bool
    attention_reasons: list[str]


def _money(amount: Decimal | float | str, currency: str) -> MoneyOut:
    out = money_to_json(Money(amount=Decimal(str(amount)), currency=currency))
    assert out is not None
    return MoneyOut(**out)


def _item(item: OrderItemModel, currency: str) -> OrderItemOut:
    return OrderItemOut(
        id=item.id,
        line_number=item.line_number,
        product_id=item.product_id,
        supplier_id=item.supplier_id,
        supplier_quote_id=item.supplier_quote_id,
        quantity=item.quantity,
        allocated_quantity=item.allocated_quantity,
        unit_price=_money(item.unit_price, currency),
        line_total=_money(item.line_total, currency),
        unit_cost=_money(item.unit_cost, currency) if item.unit_cost is not None else None,
        cost_provenance=item.cost_provenance,
        cost_source=item.cost_source,
    )


def order_out(db: Session, order: OrderModel) -> OrderOut:
    reasons = attention_reasons(db, order)
    return OrderOut(
        id=order.id,
        customer_ref=order.customer_ref,
        market=order.market,
        status=order.status,
        is_simulated=order.is_simulated,
        amount_due=_money(order.amount_due, order.currency),
        items=[_item(item, order.currency) for item in order.items],
        created_at=order.created_at,
        paid_at=order.paid_at,
        completed_at=order.completed_at,
        cancelled_at=order.cancelled_at,
        correlation_id=order.correlation_id,
        attention_required=bool(reasons),
        attention_reasons=reasons,
    )


@router.get("", response_model=list[OrderOut])
def list_orders(
    status: OrderStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[OrderOut]:
    orders = OrderService(db).list(status=status.value if status else None, limit=limit, offset=offset)
    return [order_out(db, order) for order in orders]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)) -> OrderOut:
    return order_out(db, OrderService(db).get(order_id))


@router.post("", response_model=OrderOut, status_code=201)
def create_order(
    payload: OrderCreate,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.ORDER_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> OrderOut:
    """Crea un pedido en `AWAITING_PAYMENT`. `Idempotency-Key` es obligatoria **siempre**, también en simulación:
    repetir la petición con la misma clave devuelve el mismo pedido y no crea otro."""

    def work() -> OrderOut:
        lines = [
            NewOrderLine(
                product_id=line.product_id,
                quantity=line.quantity,
                unit_price=line.unit_price.to_money(),
                supplier_quote_id=line.supplier_quote_id,
                declared_unit_cost=line.declared_unit_cost.to_money() if line.declared_unit_cost else None,
            )
            for line in payload.lines
        ]
        order = OrderService(db, settings=settings).create(
            customer_ref=payload.customer_ref,
            market=payload.market,
            lines=lines,
            actor=identity.audit_name,
        )
        return order_out(db, order)

    return run_idempotent(
        db,
        scope="orders.create",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload=payload.model_dump(),
        response=response,
        status_code=201,
        response_model=OrderOut,
        work=work,
        always_required=True,
    )
