import type { Order, OrderFulfillment, OrderPage, OrderPayment, OrderRefund } from "./api.ts";

// Vista de la pantalla de Operaciones sobre los pedidos REALES de M44 (ADR 0028 §10).
//
// Todo lo que sale de aquí se calcula a partir de lo que devuelve `GET /api/orders`: pedidos, cobros, reembolsos y
// fulfillments con sus estados y sus marcas de tiempo. No hay nada generado, ni aleatorio, ni inventado: no hay
// clientes (el pedido solo trae una referencia opaca), ni canales, ni transportistas, ni plazos prometidos, porque M44
// no los tiene. Lo que falta se muestra como ausente (`ABSENT`), nunca se rellena.
//
// Los importes se suman con enteros (`bigint`, 4 decimales): el dominio monetario no admite `float`.

const DAY_MS = 86_400_000;
const SCALE = 4;
// Sin literales `0n`: el `target` de TypeScript de esta aplicación es anterior a ES2020.
const ZERO = BigInt(0);
const SCALE_FACTOR = BigInt("1".padEnd(SCALE + 1, "0"));

// --- Dinero exacto ------------------------------------------------------------------------------------------------

export type MinorUnits = bigint;

/** `"50.0000"` → `500000n`. Rechaza lo que no sea un importe decimal exacto: nunca adivina. */
export function toMinor(amount: string): MinorUnits {
  const match = /^(-?)(\d+)(?:\.(\d{1,4}))?$/.exec(amount.trim());
  if (match === null) throw new TypeError(`not an exact amount: ${amount}`);
  const [, sign, whole, fraction = ""] = match;
  const value = BigInt(whole) * SCALE_FACTOR + BigInt(fraction.padEnd(SCALE, "0"));
  return sign === "-" ? -value : value;
}

/** Importes sumados por moneda: nunca se mezclan monedas. */
export type MoneyTotals = Map<string, MinorUnits>;

export function addTo(totals: MoneyTotals, amount: { amount: string; currency: string }): void {
  totals.set(amount.currency, (totals.get(amount.currency) ?? ZERO) + toMinor(amount.amount));
}

/** Un importe para mostrar. La conversión es solo de presentación: el cálculo ya se hizo con enteros. */
export function formatMinor(minor: MinorUnits, currency: string): string {
  const negative = minor < ZERO;
  const absolute = negative ? -minor : minor;
  const whole = absolute / SCALE_FACTOR;
  const fraction = (absolute % SCALE_FACTOR).toString().padStart(SCALE, "0");
  const decimals = fraction.endsWith("00") ? fraction.slice(0, 2) : fraction;
  const text = `${negative ? "-" : ""}${whole.toString()}.${decimals}`;
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: SCALE,
    useGrouping: true, // es-ES omite el separador de miles en 4 cifras: se fuerza, como en `lib/format.ts`
  }).format(text as unknown as number);
}

export function formatAmount(amount: { amount: string; currency: string }): string {
  return formatMinor(toMinor(amount.amount), amount.currency);
}

/** «1.000,00 €» o, con varias monedas, «1.000,00 € · 20,00 $»; `null` si no hay nada. */
export function formatTotals(totals: MoneyTotals): string | null {
  if (totals.size === 0) return null;
  return [...totals.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, minor]) => formatMinor(minor, currency))
    .join(" · ");
}

// --- Estados y su texto ----------------------------------------------------------------------------------------

export type Tone = "ok" | "warn" | "bad" | "neutral";

export const ORDER_STATUS: Record<string, { label: string; tone: Tone }> = {
  AWAITING_PAYMENT: { label: "Pendiente de cobro", tone: "warn" },
  PAID: { label: "Pagado", tone: "ok" },
  COMPLETED: { label: "Completado", tone: "ok" },
  CANCELLED: { label: "Cancelado", tone: "neutral" },
};

export const PAYMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  REQUESTED: { label: "Solicitado, nada enviado", tone: "neutral" },
  OPENING: { label: "Abriendo (pudo salir)", tone: "warn" },
  UNKNOWN_OUTCOME: { label: "Resultado desconocido", tone: "bad" },
  OPEN: { label: "Abierto", tone: "warn" },
  SUCCEEDED: { label: "Cobrado", tone: "ok" },
  FAILED: { label: "Fallido", tone: "neutral" },
  EXPIRED: { label: "Caducado", tone: "neutral" },
  DUPLICATE_CAPTURE: { label: "Cobro duplicado", tone: "bad" },
  CAPTURE_MISMATCH: { label: "Importe distinto", tone: "bad" },
};

export const REFUND_STATUS: Record<string, { label: string; tone: Tone }> = {
  REQUESTED: { label: "Solicitado, nada enviado", tone: "neutral" },
  SENDING: { label: "Enviado, sin confirmar", tone: "warn" },
  UNKNOWN_OUTCOME: { label: "Resultado desconocido", tone: "bad" },
  SUCCEEDED: { label: "Devuelto (confirmado)", tone: "ok" },
  FAILED: { label: "Fallido", tone: "neutral" },
};

export const FULFILLMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  READY: { label: "Listo, sin comprar", tone: "neutral" },
  PURCHASING: { label: "Comprando (pudo salir)", tone: "warn" },
  PURCHASED: { label: "Comprado, sin enviar", tone: "ok" },
  SHIPPING: { label: "Enviando (pudo salir)", tone: "warn" },
  SHIPPED: { label: "Enviado", tone: "ok" },
  COMPLETED: { label: "Entregado", tone: "ok" },
  FAILED: { label: "Abandonado tras fallar", tone: "neutral" },
  CANCELLED: { label: "Cancelado", tone: "neutral" },
  UNKNOWN_OUTCOME: { label: "Resultado desconocido", tone: "bad" },
};

/** Cómo se llama un estado: si el backend trae uno que esta pantalla no conoce, se muestra tal cual, nunca se oculta. */
export function describe(table: Record<string, { label: string; tone: Tone }>, status: string): { label: string; tone: Tone } {
  return table[status] ?? { label: status, tone: "neutral" };
}

export const ATTENTION_REASONS: Record<string, string> = {
  captured_on_cancelled_order: "Se cobró un pedido que estaba cancelado",
  duplicate_capture: "Hay un segundo cobro confirmado del mismo pedido",
  capture_mismatch: "El importe cobrado no coincide con el del pedido",
  open_attempt_on_settled_order: "Queda un intento de cobro abierto en un pedido ya cobrado",
  payment_outcome_unknown: "No se sabe el resultado de un intento de cobro",
  conflicting_payment_events: "Hay eventos de pago que se contradicen",
  refund_outcome_unknown: "No se sabe el resultado de un reembolso",
  refund_unconfirmed: "Un reembolso aceptado sigue sin confirmación verificada",
  fulfilment_outcome_unknown: "No se sabe el resultado de una compra o un envío",
  fulfilment_purchase_failed: "La compra al proveedor falló: reintentar, cancelar o abandonar",
  fulfilment_ship_failed: "El envío falló después de comprar: las unidades siguen compradas",
  refunded_order_in_fulfilment: "Se devolvió dinero de un pedido cuyo fulfillment sigue en curso",
};

export function attentionText(reason: string): string {
  return ATTENTION_REASONS[reason] ?? reason;
}

// --- Periodos y pestañas -----------------------------------------------------------------------------------------

export const PERIODS = [
  { value: "all", label: "Todo el historial", days: null },
  { value: "today", label: "Hoy", days: 1 },
  { value: "7d", label: "Últimos 7 días", days: 7 },
  { value: "30d", label: "Últimos 30 días", days: 30 },
] as const;

export type PeriodValue = (typeof PERIODS)[number]["value"];

/** Medianoche UTC del día de `iso`. */
export function startOfDay(iso: string): number {
  return Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
}

/** Pedidos creados dentro de la ventana de `days` días que termina hoy (`null` = todos). */
export function ordersInPeriod(orders: Order[], today: string, days: number | null): Order[] {
  if (days === null) return orders;
  const from = startOfDay(today) - (days - 1) * DAY_MS;
  return orders.filter((order) => Date.parse(order.created_at) >= from);
}

export const TABS: { key: string; label: string; match: (order: Order) => boolean }[] = [
  { key: "todos", label: "Todos", match: () => true },
  { key: "atencion", label: "Requieren atención", match: (o) => o.attention_required },
  { key: "cobro", label: "Pendientes de cobro", match: (o) => o.status === "AWAITING_PAYMENT" },
  { key: "pagados", label: "Pagados", match: (o) => o.status === "PAID" },
  { key: "completados", label: "Completados", match: (o) => o.status === "COMPLETED" },
  { key: "cancelados", label: "Cancelados", match: (o) => o.status === "CANCELLED" },
];

/** Más recientes primero; a igual instante, por id, para que servidor y navegador ordenen igual. */
export function newestFirst(orders: Order[]): Order[] {
  return [...orders].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || a.id.localeCompare(b.id));
}

// --- Lo cargado frente a lo que existe -----------------------------------------------------------------------------
//
// `GET /api/orders` entrega páginas (M45, P2-2). Esta pantalla solo ve **las que ha cargado**, que son siempre un
// prefijo del historial —los más recientes—: ninguna cifra calculada sobre ellas es «del total» mientras el backend
// diga que hay más. Cada cifra es **completa** (cubre todos los pedidos que existen en su ámbito) o **parcial** (solo
// los cargados), y se enseña como lo que es. Nunca se inventa un total a partir de una muestra.

export interface OrdersLoaded {
  orders: Order[];
  /** El backend dice que existen pedidos más antiguos que el último cargado. */
  hasMore: boolean;
  /** De dónde sigue la siguiente página; `null` si no hay más. */
  nextCursor: string | null;
}

export function loadedFromPage(page: Pick<OrderPage, "items" | "has_more" | "next_cursor">): OrdersLoaded {
  return { orders: page.items, hasMore: page.has_more, nextCursor: page.next_cursor };
}

/** Une una página a lo ya cargado. El backend no repite pedidos, pero esta pantalla no lo da por hecho: un pedido ya
 * presente no se cuenta dos veces, y los pedidos van siempre del más reciente al más antiguo. */
export function appendPage(
  loaded: OrdersLoaded,
  page: Pick<OrderPage, "items" | "has_more" | "next_cursor">,
): OrdersLoaded {
  const known = new Set(loaded.orders.map((order) => order.id));
  const added = page.items.filter((order) => !known.has(order.id));
  return {
    orders: newestFirst([...loaded.orders, ...added]),
    hasMore: page.has_more,
    nextCursor: page.next_cursor,
  };
}

/** `complete`: la cifra cubre **todos** los pedidos del ámbito. `partial`: solo los cargados; hay más sin cargar. */
export type Coverage = "complete" | "partial";

/** ¿Lo cargado cubre todos los pedidos de este periodo? Con todo cargado, sí. Si no, solo cuando el pedido **más
 * antiguo** cargado es **anterior** al comienzo del periodo (estrictamente: a igual instante podría haber otro sin
 * cargar): los pedidos van del más reciente al más antiguo, así que todo lo que cae dentro del periodo ya está. */
export function periodCoverage(loaded: OrdersLoaded, today: string, days: number | null): Coverage {
  if (!loaded.hasMore) return "complete";
  if (days === null || loaded.orders.length === 0) return "partial";
  const from = startOfDay(today) - (days - 1) * DAY_MS;
  const oldest = Math.min(...loaded.orders.map((order) => Date.parse(order.created_at)));
  return oldest < from ? "complete" : "partial";
}

/** Un contador: «12», o «12+» si hay más pedidos sin cargar (es un mínimo, no un total). */
export function countText(formatted: string, coverage: Coverage): string {
  return coverage === "partial" ? `${formatted}+` : formatted;
}

/** La frase que dice qué se está viendo. Nunca «X de Y»: el total no se conoce. */
export function loadedSummary(count: number, hasMore: boolean): string {
  const noun = count === 1 ? "pedido" : "pedidos";
  return hasMore
    ? `Mostrando ${count} ${noun} · hay más resultados sin cargar`
    : `${count} ${noun} · son todos los que existen`;
}

/** Lo que se avisa en una cifra parcial. */
export const PARTIAL_FIGURE_NOTE = "Solo de los pedidos cargados; hay más sin cargar";

/** Qué le pasó a la petición de una página, dicho con las palabras de cada causa: un fallo del backend no es una
 * petición inválida, y ninguna de las dos es una página vacía. */
export function pageErrorText(status: number | undefined, message: string): string {
  if (status === 400 || status === 422) {
    return "El backend rechazó la petición de la siguiente página por no ser válida. Recarga la pantalla para empezar de nuevo.";
  }
  if (status === 401 || status === 403) {
    return "No tienes permiso para leer más pedidos, o la sesión ha caducado.";
  }
  if (status === undefined) {
    return `No se pudo contactar con el backend: ${message}`;
  }
  return `El backend falló al leer la siguiente página (HTTP ${status}). Lo ya cargado no se ha perdido: puedes reintentar.`;
}

// --- Cifras ---------------------------------------------------------------------------------------------------

export interface OrderKpis {
  total: number;
  awaitingPayment: number;
  paid: number;
  completed: number;
  cancelled: number;
  attention: number;
  /** Dinero realmente cobrado (la evidencia financiera), por moneda. */
  captured: MoneyTotals;
  /** Reembolsos con un hecho verificado que los confirma. */
  refunded: MoneyTotals;
  /** Reembolsos pedidos y todavía sin confirmar: dinero apartado, no devuelto. */
  refundInProgress: MoneyTotals;
}

export function orderKpis(orders: Order[]): OrderKpis {
  const captured: MoneyTotals = new Map();
  const refunded: MoneyTotals = new Map();
  const refundInProgress: MoneyTotals = new Map();
  for (const order of orders) {
    for (const payment of order.payments) {
      addTo(captured, payment.captured_amount);
      addTo(refunded, payment.refunded_amount);
      const pending = toMinor(payment.refund_committed_amount.amount) - toMinor(payment.refunded_amount.amount);
      if (pending > ZERO) {
        refundInProgress.set(
          payment.refund_committed_amount.currency,
          (refundInProgress.get(payment.refund_committed_amount.currency) ?? ZERO) + pending,
        );
      }
    }
  }
  const count = (status: string) => orders.filter((o) => o.status === status).length;
  return {
    total: orders.length,
    awaitingPayment: count("AWAITING_PAYMENT"),
    paid: count("PAID"),
    completed: count("COMPLETED"),
    cancelled: count("CANCELLED"),
    attention: orders.filter((o) => o.attention_required).length,
    captured,
    refunded,
    refundInProgress,
  };
}

export interface PipelineStage {
  status: string;
  label: string;
  count: number;
}

/** Orden del recorrido de un fulfillment; los estados de salida del recorrido van al final. */
const PIPELINE_ORDER = [
  "READY",
  "PURCHASING",
  "PURCHASED",
  "SHIPPING",
  "SHIPPED",
  "COMPLETED",
  "UNKNOWN_OUTCOME",
  "FAILED",
  "CANCELLED",
];

/** Cuántos fulfillments hay en cada estado. Un estado que el backend añada y esta pantalla no conozca aparece igualmente. */
export function fulfilmentPipeline(orders: Order[]): PipelineStage[] {
  const counts = new Map<string, number>();
  for (const order of orders) {
    for (const fulfillment of order.fulfillments) counts.set(fulfillment.status, (counts.get(fulfillment.status) ?? 0) + 1);
  }
  const known = PIPELINE_ORDER.map((status) => ({ status, label: describe(FULFILLMENT_STATUS, status).label, count: counts.get(status) ?? 0 }));
  const unknown = [...counts.keys()]
    .filter((status) => !PIPELINE_ORDER.includes(status))
    .sort()
    .map((status) => ({ status, label: status, count: counts.get(status) ?? 0 }));
  return [...known, ...unknown];
}

export function fulfilmentTotal(orders: Order[]): number {
  return orders.reduce((sum, order) => sum + order.fulfillments.length, 0);
}

/** Pedidos que piden mirada humana, los de más motivos primero. */
export function attentionList(orders: Order[]): Order[] {
  return newestFirst(orders.filter((o) => o.attention_required)).sort((a, b) => b.attention_reasons.length - a.attention_reasons.length);
}

// --- La historia de un pedido, con sus marcas de tiempo reales ---------------------------------------------------------

export interface OrderEvent {
  at: string;
  label: string;
  detail?: string;
}

function paymentEvents(payment: OrderPayment): OrderEvent[] {
  const events: OrderEvent[] = [{ at: payment.created_at, label: `Intento de cobro ${payment.attempt_number} solicitado` }];
  if (payment.opened_at) events.push({ at: payment.opened_at, label: `Intento ${payment.attempt_number} abierto en el proveedor` });
  if (payment.succeeded_at) {
    events.push({ at: payment.succeeded_at, label: `Cobro ${payment.attempt_number} confirmado`, detail: formatAmount(payment.captured_amount) });
  }
  if (payment.closed_at && !payment.succeeded_at) {
    events.push({ at: payment.closed_at, label: `Intento ${payment.attempt_number} cerrado`, detail: describe(PAYMENT_STATUS, payment.status).label });
  }
  return events;
}

function refundEvents(refund: OrderRefund): OrderEvent[] {
  const events: OrderEvent[] = [{ at: refund.requested_at, label: "Reembolso solicitado", detail: formatAmount(refund.amount) }];
  if (refund.finished_at) {
    events.push({ at: refund.finished_at, label: `Reembolso ${describe(REFUND_STATUS, refund.status).label.toLowerCase()}`, detail: formatAmount(refund.amount) });
  }
  return events;
}

function fulfilmentEvents(fulfillment: OrderFulfillment, index: number): OrderEvent[] {
  const tag = `Fulfillment ${index + 1}`;
  const events: OrderEvent[] = [{ at: fulfillment.created_at, label: `${tag} creado`, detail: `${fulfillment.items.reduce((n, i) => n + i.quantity, 0)} unidades` }];
  if (fulfillment.purchased_at) events.push({ at: fulfillment.purchased_at, label: `${tag}: comprado al proveedor` });
  if (fulfillment.shipped_at) events.push({ at: fulfillment.shipped_at, label: `${tag}: enviado` });
  if (fulfillment.completed_at) events.push({ at: fulfillment.completed_at, label: `${tag}: entrega confirmada`, detail: fulfillment.completed_by ?? undefined });
  return events;
}

/** Todo lo que le pasó al pedido, en orden. Solo hechos con fecha en la base de datos: lo que no tiene fecha no sale. */
export function orderEvents(order: Order): OrderEvent[] {
  const events: OrderEvent[] = [{ at: order.created_at, label: "Pedido creado" }];
  if (order.paid_at) events.push({ at: order.paid_at, label: "Pedido pagado" });
  for (const payment of order.payments) events.push(...paymentEvents(payment));
  order.fulfillments.forEach((fulfillment, index) => events.push(...fulfilmentEvents(fulfillment, index)));
  for (const refund of order.refunds) events.push(...refundEvents(refund));
  if (order.completed_at) events.push({ at: order.completed_at, label: "Pedido completado" });
  if (order.cancelled_at) events.push({ at: order.cancelled_at, label: "Pedido cancelado" });
  return events.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

// --- Lo que Operaciones todavía no puede mostrar --------------------------------------------------------------------

/** Lo que el antiguo Control Tower enseñaba y M44 no tiene. Se dice, en vez de rellenarlo. */
export const ABSENT: { key: string; title: string; why: string }[] = [
  {
    key: "carriers",
    title: "Transportistas y seguimiento del envío",
    why: "No hay ningún transportista conectado: el envío es una operación simulada y solo deja su fecha y una referencia.",
  },
  {
    key: "returns",
    title: "Devoluciones físicas",
    why: "M44 devuelve dinero (reembolsos), no mercancía. Una devolución física todavía no existe como proceso.",
  },
  {
    key: "sla",
    title: "Plazos prometidos y cumplimiento (SLA)",
    why: "Ningún pedido lleva una entrega prometida, así que no se puede medir si se cumplió.",
  },
  {
    key: "suppliers",
    title: "Rendimiento por proveedor",
    why: "No hay entregas reales de proveedor de las que sacar puntualidad ni defectos.",
  },
  {
    key: "customers",
    title: "Clientes y canal de venta",
    why: "El pedido solo guarda una referencia opaca del cliente: ni nombre, ni correo, ni canal. Es una decisión de privacidad.",
  },
  {
    key: "automations",
    title: "Automatizaciones",
    why: "No existe ninguna: cada compra y cada envío los ordena una persona.",
  },
];
