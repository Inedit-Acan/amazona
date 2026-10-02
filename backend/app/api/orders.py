"""Pedidos (Milestone 44, ADR 0028).

Aquí un pedido se crea y se lee. **No hay ninguna ruta que lo marque como pagado**: eso lo decide un evento de
pago verificado (`PaymentService`) y nada más. Las lecturas no escriben.
"""

import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.db.models.fulfillment import Fulfillment as FulfillmentModel
from app.db.models.fulfillment import FulfillmentItem as FulfillmentItemModel
from app.db.models.order import Order as OrderModel
from app.db.models.order import OrderItem as OrderItemModel
from app.db.models.payment import Payment as PaymentModel
from app.db.models.payment import Refund as RefundModel
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.money.money import Money
from app.money.serialization import money_to_json
from app.orders.attention import attention_reasons
from app.orders.domain import OrderStatus
from app.orders.fulfilment import FulfilmentRequestLine, FulfilmentService
from app.orders.payment_attempts import PaymentAttemptService, Requester
from app.orders.refunds import RefundService
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


class RefundCreate(BaseModel):
    """Devolver parte o todo de un cobro. Un motivo de una lista cerrada; nunca texto libre."""

    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(min_length=1, max_length=36)
    amount: MoneyIn
    reason: str = Field(min_length=1, max_length=32)


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


class PaymentOut(BaseModel):
    id: str
    attempt_number: int
    provider: str
    #: `REQUESTED` (nada enviado) · `OPENING` (pudo salir) · `UNKNOWN_OUTCOME` · `OPEN` · `SUCCEEDED` · `FAILED` ·
    #: `EXPIRED` · `DUPLICATE_CAPTURE` · `CAPTURE_MISMATCH`.
    status: str
    amount: MoneyOut
    captured_amount: MoneyOut
    refund_committed_amount: MoneyOut
    refunded_amount: MoneyOut
    provider_payment_ref: str | None
    duplicate_of_payment_id: str | None
    last_failure_code: str | None
    opened_at: datetime.datetime | None
    succeeded_at: datetime.datetime | None
    closed_at: datetime.datetime | None
    created_at: datetime.datetime


class RefundOut(BaseModel):
    id: str
    payment_id: str
    origin: str
    status: str
    amount: MoneyOut
    reason: str
    provider_refund_ref: str | None
    failure_code: str | None
    requested_at: datetime.datetime
    finished_at: datetime.datetime | None


class FulfilmentItemOut(BaseModel):
    order_item_id: str
    line_number: int
    quantity: int


class FulfilmentOut(BaseModel):
    id: str
    order_id: str
    provider: str
    supplier_id: str | None
    #: `READY` · `PURCHASING` · `PURCHASED` · `SHIPPING` · `SHIPPED` · `COMPLETED` · `FAILED` · `CANCELLED` ·
    #: `UNKNOWN_OUTCOME` (con `unknown_phase`).
    status: str
    unknown_phase: str | None
    purchase_reference: str | None
    tracking_reference: str | None
    failed_attempts: int
    last_failure_code: str | None
    items: list[FulfilmentItemOut]
    created_by: str
    completed_by: str | None
    created_at: datetime.datetime
    purchased_at: datetime.datetime | None
    shipped_at: datetime.datetime | None
    completed_at: datetime.datetime | None


class OrderOut(BaseModel):
    id: str
    customer_ref: str
    market: str
    status: str
    is_simulated: bool
    amount_due: MoneyOut
    items: list[OrderItemOut]
    payments: list[PaymentOut] = Field(default_factory=list)
    refunds: list[RefundOut] = Field(default_factory=list)
    fulfillments: list[FulfilmentOut] = Field(default_factory=list)
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


def payment_out(payment: PaymentModel) -> PaymentOut:
    cur = payment.currency
    return PaymentOut(
        id=payment.id,
        attempt_number=payment.attempt_number,
        provider=payment.provider,
        status=payment.status,
        amount=_money(payment.amount, cur),
        captured_amount=_money(payment.captured_amount, cur),
        refund_committed_amount=_money(payment.refund_committed_amount, cur),
        refunded_amount=_money(payment.refunded_amount, cur),
        provider_payment_ref=payment.provider_payment_ref,
        duplicate_of_payment_id=payment.duplicate_of_payment_id,
        last_failure_code=payment.last_failure_code,
        opened_at=payment.opened_at,
        succeeded_at=payment.succeeded_at,
        closed_at=payment.closed_at,
        created_at=payment.created_at,
    )


def refund_out(refund: RefundModel) -> RefundOut:
    return RefundOut(
        id=refund.id,
        payment_id=refund.payment_id,
        origin=refund.origin,
        status=refund.status,
        amount=_money(refund.amount, refund.currency),
        reason=refund.reason,
        provider_refund_ref=refund.provider_refund_ref,
        failure_code=refund.failure_code,
        requested_at=refund.requested_at,
        finished_at=refund.finished_at,
    )


def fulfillment_out(db: Session, fulfillment: FulfillmentModel) -> FulfilmentOut:
    numbers = {
        item.id: item.line_number
        for item in db.scalars(select(OrderItemModel).where(OrderItemModel.order_id == fulfillment.order_id))
    }
    items = db.scalars(
        select(FulfillmentItemModel)
        .where(FulfillmentItemModel.fulfillment_id == fulfillment.id)
        .order_by(FulfillmentItemModel.created_at, FulfillmentItemModel.id)
    ).all()
    return FulfilmentOut(
        id=fulfillment.id,
        order_id=fulfillment.order_id,
        provider=fulfillment.provider,
        supplier_id=fulfillment.supplier_id,
        status=fulfillment.status,
        unknown_phase=fulfillment.unknown_phase,
        purchase_reference=fulfillment.purchase_reference,
        tracking_reference=fulfillment.tracking_reference,
        failed_attempts=fulfillment.failed_attempts,
        last_failure_code=fulfillment.last_failure_code,
        items=[
            FulfilmentItemOut(
                order_item_id=item.order_item_id, line_number=numbers[item.order_item_id], quantity=item.quantity
            )
            for item in items
        ],
        created_by=fulfillment.created_by,
        completed_by=fulfillment.completed_by,
        created_at=fulfillment.created_at,
        purchased_at=fulfillment.purchased_at,
        shipped_at=fulfillment.shipped_at,
        completed_at=fulfillment.completed_at,
    )


def order_out(db: Session, order: OrderModel) -> OrderOut:
    reasons = attention_reasons(db, order)
    payments = list(
        db.scalars(select(PaymentModel).where(PaymentModel.order_id == order.id).order_by(PaymentModel.attempt_number))
    )
    refunds = (
        list(
            db.scalars(
                select(RefundModel)
                .where(RefundModel.payment_id.in_([p.id for p in payments]))
                .order_by(RefundModel.requested_at, RefundModel.id)
            )
        )
        if payments
        else []
    )
    return OrderOut(
        id=order.id,
        customer_ref=order.customer_ref,
        market=order.market,
        status=order.status,
        is_simulated=order.is_simulated,
        amount_due=_money(order.amount_due, order.currency),
        items=[_item(item, order.currency) for item in order.items],
        payments=[payment_out(p) for p in payments],
        refunds=[refund_out(r) for r in refunds],
        fulfillments=[
            fulfillment_out(db, f)
            for f in db.scalars(
                select(FulfillmentModel)
                .where(FulfillmentModel.order_id == order.id)
                .order_by(FulfillmentModel.created_at, FulfillmentModel.id)
            )
        ],
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


@router.post("/{order_id}/payments", response_model=PaymentOut, status_code=201)
def start_payment_attempt(
    order_id: str,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.PAYMENT_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> PaymentOut:
    """Abre un intento de cobro del pedido: una acción externa que pasa por el ActionGate y por `ExternalAction`.

    La misma `Idempotency-Key` es **la misma intención** (devuelve el mismo intento); una clave nueva es un intento
    nuevo, y solo se admite si el anterior ya terminó. El resultado puede ser un intento `OPEN`, `FAILED` o
    `UNKNOWN_OUTCOME`: esto último **bloquea** los intentos siguientes hasta reconciliarse. El pago no se confirma
    aquí: lo confirma un evento verificado."""

    def work() -> PaymentOut:
        payment = PaymentAttemptService(db, settings=settings).start(
            order_id, requester=Requester(name=identity.audit_name, role=identity.role.value if identity.role else None)
        )
        return payment_out(payment)

    return run_idempotent(
        db,
        scope="orders.payment",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"order_id": order_id},
        response=response,
        status_code=201,
        response_model=PaymentOut,
        work=work,
        always_required=True,
    )


@router.post("/{order_id}/refunds", response_model=RefundOut, status_code=201)
def request_refund(
    order_id: str,
    payload: RefundCreate,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.REFUND_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> RefundOut:
    """Devuelve dinero de un cobro con dinero capturado: una acción externa que pasa por el ActionGate y por
    `ExternalAction`, y que solo ordena una persona con permiso. Lo que se aparta del cobro no puede pasar de lo
    capturado, aunque lleguen dos peticiones a la vez.

    La misma `Idempotency-Key` es **la misma intención** (devuelve el mismo reembolso); otra clave, con el mismo
    importe, es otro reembolso. El resultado puede ser `SENDING` (aceptado, a la espera de que el proveedor lo
    confirme con un hecho verificado), `UNKNOWN_OUTCOME` (bloquea nuevos reembolsos de ese cobro) o `FAILED`. Esta
    ruta nunca da por devuelto el dinero."""

    def work() -> RefundOut:
        refund = RefundService(db, settings=settings).request(
            payload.payment_id,
            amount=payload.amount.to_money(),
            reason=payload.reason,
            requester=Requester(name=identity.audit_name, role=identity.role.value if identity.role else None),
            order_id=order_id,
        )
        return refund_out(refund)

    return run_idempotent(
        db,
        scope="orders.refund",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"order_id": order_id, **payload.model_dump()},
        response=response,
        status_code=201,
        response_model=RefundOut,
        work=work,
        always_required=True,
    )


class FulfilmentLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_item_id: str = Field(min_length=1, max_length=36)
    quantity: int = Field(ge=1)


class FulfilmentCreate(BaseModel):
    """Qué líneas (y cuántas unidades de cada una) cubrirá un fulfillment. Ni un dato personal: no hay envíos reales."""

    model_config = ConfigDict(extra="forbid")

    lines: list[FulfilmentLineIn] = Field(min_length=1)


@router.post("/{order_id}/fulfillments", response_model=FulfilmentOut, status_code=201)
def create_fulfillment(
    order_id: str,
    payload: FulfilmentCreate,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.FULFILMENT_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> FulfilmentOut:
    """Reparte unidades de un pedido **pagado** en un fulfillment `READY`: una decisión local, sin efecto fuera. Las
    unidades se apartan con aritmética de base de datos, así que ninguna línea se asigna de más. La misma
    `Idempotency-Key` devuelve el mismo fulfillment."""

    def work() -> FulfilmentOut:
        fulfillment = FulfilmentService(db, settings=settings).create(
            order_id,
            [FulfilmentRequestLine(line.order_item_id, line.quantity) for line in payload.lines],
            actor=identity.audit_name,
        )
        return fulfillment_out(db, fulfillment)

    return run_idempotent(
        db,
        scope="orders.fulfillment",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"order_id": order_id, **payload.model_dump()},
        response=response,
        status_code=201,
        response_model=FulfilmentOut,
        work=work,
        always_required=True,
    )


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: str,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.ORDER_WRITE)),
) -> OrderOut:
    """Cancela un pedido que nunca se cobró. Es una transición de estado con compare-and-set: repetirla es un 409."""
    return order_out(db, OrderService(db).cancel(order_id, actor=identity.audit_name))
