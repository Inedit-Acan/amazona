"""Crear y leer pedidos (Milestone 44, ADR 0028).

Este servicio **no cobra ni paga**: un pedido nace en `AWAITING_PAYMENT`, y solo un evento de pago verificado, por
`PaymentService`, lo pasa a `PAID`. Aquí no existe ninguna función que marque un pedido como pagado.

Lo que sí hace es no inventar nada: el importe a cobrar es la suma de las líneas (sin envío ni impuestos, que no
existen todavía), el coste de proveedor de una línea es el de su cotización **si está en la misma moneda** o el
que declara quien crea el pedido, y si no se sabe se queda desconocido (`NULL`), nunca cero.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.supplier_quote import SupplierQuote
from app.money.money import Money, total
from app.orders.domain import (
    MAX_LINES_PER_ORDER,
    MAX_QUANTITY_PER_LINE,
    OrderStatus,
    require_cents,
    validate_customer_ref,
)

ORDER_ACTOR = "orders"


@dataclass(frozen=True)
class NewOrderLine:
    """Lo que se pide en una línea. El precio de venta lo decide quien crea el pedido (la web pública, algún día)."""

    product_id: str
    quantity: int
    unit_price: Money
    #: La cotización del proveedor a la que se compraría. Opcional.
    supplier_quote_id: str | None = None
    #: Un coste de proveedor declarado por quien crea el pedido. Si lo hay, manda sobre el de la cotización.
    declared_unit_cost: Money | None = None


class OrderService:
    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self._db = db
        self._settings = settings or get_settings()

    # --- Crear ---------------------------------------------------------------------------------

    def create(
        self,
        *,
        customer_ref: str,
        market: str,
        lines: Sequence[NewOrderLine],
        actor: str,
        correlation_id: str | None = None,
    ) -> Order:
        simulated = self._settings.operating_in_simulation
        validate_customer_ref(customer_ref, simulated=simulated)
        market = (market or "").strip().lower()
        if not market or len(market) > 16:
            raise ValidationError("market must be a short, non-empty identifier")
        if not 1 <= len(lines) <= MAX_LINES_PER_ORDER:
            raise ValidationError(f"an order has between 1 and {MAX_LINES_PER_ORDER} lines")

        currency = lines[0].unit_price.currency
        items: list[OrderItem] = []
        for number, line in enumerate(lines, start=1):
            items.append(self._item(line, number=number, currency=currency, actor=actor))
        amount_due = total([Money.of(str(i.line_total), currency) for i in items], currency=currency)

        order = Order(
            customer_ref=customer_ref,
            market=market,
            currency=currency,
            amount_due=amount_due.amount,
            status=OrderStatus.AWAITING_PAYMENT.value,
            is_simulated=simulated,
            correlation_id=correlation_id or new_correlation_id(),
            items=items,
        )
        self._db.add(order)
        self._db.flush()
        self._db.add(
            AuditLog(
                actor=actor,
                action="order.created",
                resource=f"order:{order.id}",
                before=None,
                after={
                    "customer_ref": customer_ref,
                    "market": market,
                    "currency": currency,
                    "amount_due": str(amount_due.amount),
                    "lines": len(items),
                    "simulated": simulated,
                },
                correlation_id=order.correlation_id,
            )
        )
        self._db.commit()
        return order

    def _item(self, line: NewOrderLine, *, number: int, currency: str, actor: str) -> OrderItem:
        if not 1 <= line.quantity <= MAX_QUANTITY_PER_LINE:
            raise ValidationError(f"line {number}: quantity must be between 1 and {MAX_QUANTITY_PER_LINE}")
        if line.unit_price.currency != currency:
            raise ValidationError(f"line {number}: every line of an order is in {currency}; nothing is converted")
        require_cents(line.unit_price, f"line {number}: the unit price")
        if line.unit_price.amount <= 0:
            raise ValidationError(f"line {number}: the unit price must be greater than zero")
        if self._db.get(Product, line.product_id) is None:
            raise NotFoundError(f"product {line.product_id} not found")

        supplier_id: str | None = None
        unit_cost: Money | None = None
        provenance: str | None = None
        source: str | None = None

        quote = self._quote(line, number)
        if quote is not None:
            supplier_id = quote.supplier_id
            # Solo el coste en la misma moneda: otra moneda sin convertir es un coste desconocido, no un cambio a 1:1.
            if quote.unit_price is not None and quote.currency == currency:
                unit_cost = Money.from_legacy_float(quote.unit_price, currency)
                provenance = quote.provenance or "supplier_quote"
                source = f"supplier_quote:{quote.id}"
        if line.declared_unit_cost is not None:
            if line.declared_unit_cost.currency != currency:
                raise ValidationError(f"line {number}: a declared cost is in {currency} too; nothing is converted")
            if line.declared_unit_cost.is_negative:
                raise ValidationError(f"line {number}: a cost cannot be negative")
            unit_cost = line.declared_unit_cost
            provenance = "declared"
            source = f"manual:{actor}"

        return OrderItem(
            line_number=number,
            product_id=line.product_id,
            supplier_id=supplier_id,
            supplier_quote_id=line.supplier_quote_id,
            quantity=line.quantity,
            allocated_quantity=0,
            unit_price=line.unit_price.amount,
            line_total=(line.unit_price * line.quantity).amount,
            unit_cost=unit_cost.amount if unit_cost is not None else None,
            cost_provenance=provenance,
            cost_source=source,
        )

    def _quote(self, line: NewOrderLine, number: int) -> SupplierQuote | None:
        if line.supplier_quote_id is None:
            return None
        quote = self._db.get(SupplierQuote, line.supplier_quote_id)
        if quote is None:
            raise NotFoundError(f"supplier quote {line.supplier_quote_id} not found")
        if quote.product_id != line.product_id:
            raise ValidationError(f"line {number}: the supplier quote belongs to another product")
        return quote

    # --- Leer (no escribe nunca) -----------------------------------------------------------------

    def get(self, order_id: str) -> Order:
        order = self._db.get(Order, order_id)
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        return order

    def list(self, *, status: str | None = None, limit: int = 100, offset: int = 0) -> list[Order]:
        query = select(Order).order_by(Order.created_at.desc(), Order.id)
        if status is not None:
            query = query.where(Order.status == status)
        return list(self._db.scalars(query.limit(limit).offset(offset)))
