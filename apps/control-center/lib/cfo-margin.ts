import type { Order, RevenueEntry } from "./api.ts";
import { add, isZero, multiplyByCount, parseDecimal, subtract, toText, ZERO, type Decimal } from "./decimal.ts";
import { declared, verified, type Declared, type Verified } from "./provenance.ts";

// Coste declarado y margen de contribución declarado (M45, Commit 10).
//
//   margen de contribución declarado = ingreso verificado − reembolsos verificados − coste declarado del pedido
//
// Las dos primeras magnitudes son HECHOS del registro (ADR 0030). La tercera es un dato DECLARADO: el backend guarda
// `unit_cost` de cada línea con su `cost_provenance` (`supplier_quote` o `declared`) y su `cost_source`, y lo deja en
// `null` cuando nadie lo ha dicho — un coste desconocido no es un coste cero.
//
// Por eso el resultado se etiqueta **declarado**, nunca verificado: una cifra no puede ser más fiable que el menos
// fiable de sus ingredientes. Y por eso sólo existe cuando:
//
//   1. el pedido está en la moneda contable (EUR, D3 del ADR 0030): aquí no se convierte ninguna divisa;
//   2. TODAS sus líneas tienen `unit_cost` conocido;
//   3. ese coste trae su procedencia declarada;
//   4. no falta ninguna magnitud necesaria (ni un pedido que no se haya podido leer).
//
// Si falta cualquier coste, el margen es `null` y la pantalla dice «Cobertura de costes incompleta». Nunca se estima,
// nunca se asume cero, nunca se completa con constantes y nunca se llama beneficio.

/** La única moneda que se consolida (D3 del ADR 0030). Lo demás se enseña aparte y no se convierte. */
export const ACCOUNTING_CURRENCY = "EUR";

/** Lo verificado del registro es sólo `ORDER_PAYMENT`; un duplicado o una discrepancia nunca entra aquí. */
const VERIFIED_CLASSIFICATION = "ORDER_PAYMENT";

export interface OrderMargin {
  orderId: string;
  currency: string;
  /** Marcado por el backend como pedido de simulación. A diferencia del registro, el pedido SÍ lo sabe. */
  isSimulated: boolean;
  revenue: Verified<Decimal>;
  refunds: Verified<Decimal>;
  net: Verified<Decimal>;
  /** Coste declarado del pedido; `null` = alguna línea no tiene coste conocido. */
  cost: Declared<Decimal> | null;
  /** Margen de contribución declarado; `null` cuando el coste no se conoce entero. */
  margin: Declared<Decimal> | null;
  lines: number;
  linesWithCost: number;
  /** Las procedencias distintas del coste de las líneas (`supplier_quote`, `declared`…). */
  costProvenances: string[];
}

export interface CostCoverage {
  /** Pedidos con ingreso verificado en la moneda contable dentro del periodo. */
  orders: number;
  /** De ésos, cuántos se pudieron leer. Un pedido que no se leyó es coste desconocido, no coste cero. */
  ordersRead: number;
  lines: number;
  linesWithCost: number;
  /** Porcentaje de líneas con coste conocido, sobre los pedidos leídos (0 si no hay ninguna línea). */
  percent: number;
  /** Todo lo necesario está: se puede agregar un margen. */
  complete: boolean;
}

export interface MarginSummary {
  coverage: CostCoverage;
  /** Margen de contribución declarado del periodo. **Sólo existe con cobertura del 100 %.** */
  margin: Declared<Decimal> | null;
  /** Por qué no hay margen, cuando no lo hay. */
  blockedBy: "no_orders" | "orders_not_read" | "missing_costs" | "entries_incomplete" | null;
  revenue: Verified<Decimal> | null;
  refunds: Verified<Decimal> | null;
  net: Verified<Decimal> | null;
  cost: Declared<Decimal> | null;
  /** Fila por pedido, del de más ingreso al de menos. */
  orders: OrderMargin[];
  /** Pedidos con ingreso verificado en otra moneda: se enseñan aparte y no se suman ni se convierten. */
  otherCurrencies: string[];
  /** Cuántos de los pedidos leídos están marcados como simulados. */
  simulated: number;
}

interface Totals {
  revenue: Decimal;
  refunds: Decimal;
  currency: string;
}

/** Ingreso y reembolso **verificados** por pedido, a partir de las entradas del registro. */
function byOrder(entries: RevenueEntry[]): Map<string, Totals> {
  const totals = new Map<string, Totals>();
  for (const entry of entries) {
    if (entry.classification !== VERIFIED_CLASSIFICATION) continue;
    const amount = parseDecimal(entry.amount);
    if (amount === null) continue; // un importe que no es decimal no se adivina: no entra
    const current = totals.get(entry.order_id) ?? { revenue: ZERO, refunds: ZERO, currency: entry.currency };
    // Un pedido con entradas en dos monedas no es agregable: se marca y se descarta más abajo.
    const currency = current.currency === entry.currency ? current.currency : "";
    totals.set(entry.order_id, {
      currency,
      revenue: entry.kind === "CAPTURE" ? add(current.revenue, amount) : current.revenue,
      refunds: entry.kind === "REFUND" ? add(current.refunds, amount) : current.refunds,
    });
  }
  return totals;
}

/** Coste declarado de un pedido: `Σ unit_cost × quantity`. `null` si alguna línea no tiene coste conocido. */
export function declaredCost(order: Order): { cost: Decimal | null; lines: number; withCost: number; provenances: string[] } {
  let cost: Decimal = ZERO;
  let withCost = 0;
  const provenances = new Set<string>();
  for (const item of order.items) {
    if (item.unit_cost === null || item.cost_provenance === null) continue; // coste desconocido
    if (item.unit_cost.currency !== order.amount_due.currency) continue; // otra moneda: no se convierte
    const unit = parseDecimal(item.unit_cost.amount);
    const line = unit === null ? null : multiplyByCount(unit, item.quantity);
    if (line === null) continue;
    cost = add(cost, line);
    withCost += 1;
    provenances.add(item.cost_provenance);
  }
  const lines = order.items.length;
  return {
    cost: lines > 0 && withCost === lines ? cost : null,
    lines,
    withCost,
    provenances: [...provenances].sort(),
  };
}

/** El margen de contribución declarado del periodo, y por qué no existe cuando no existe.
 *
 * `entriesComplete` dice si las entradas que se pasan son TODAS las del periodo: con una lista truncada no se puede
 * afirmar el ingreso de un pedido, así que no hay margen agregado. */
export function marginSummary(
  entries: RevenueEntry[],
  orders: Order[],
  { entriesComplete }: { entriesComplete: boolean },
): MarginSummary {
  const totals = byOrder(entries);
  const known = new Map(orders.map((order) => [order.id, order] as const));

  const rows: OrderMargin[] = [];
  const others = new Set<string>();
  let orderCount = 0;
  let ordersRead = 0;
  let lines = 0;
  let linesWithCost = 0;
  let simulated = 0;

  for (const [orderId, total] of totals) {
    if (total.currency !== ACCOUNTING_CURRENCY) {
      if (total.currency !== "") others.add(total.currency);
      continue; // otra moneda (o varias): fuera del agregado, nunca convertida
    }
    orderCount += 1;
    const order = known.get(orderId);
    const net = subtract(total.revenue, total.refunds);
    if (order === undefined) {
      rows.push({
        orderId,
        currency: total.currency,
        isSimulated: false,
        revenue: verified(total.revenue),
        refunds: verified(total.refunds),
        net: verified(net),
        cost: null,
        margin: null,
        lines: 0,
        linesWithCost: 0,
        costProvenances: [],
      });
      continue;
    }
    ordersRead += 1;
    if (order.is_simulated) simulated += 1;
    const cost = declaredCost(order);
    lines += cost.lines;
    linesWithCost += cost.withCost;
    rows.push({
      orderId,
      currency: total.currency,
      isSimulated: order.is_simulated,
      revenue: verified(total.revenue),
      refunds: verified(total.refunds),
      net: verified(net),
      cost: cost.cost === null ? null : declared(cost.cost),
      // La única combinación que cruza procedencias, y degrada a «declarado».
      margin: cost.cost === null ? null : declared(subtract(net, cost.cost)),
      lines: cost.lines,
      linesWithCost: cost.withCost,
      costProvenances: cost.provenances,
    });
  }

  rows.sort((a, b) => (b.revenue.value.units > a.revenue.value.units ? 1 : b.revenue.value.units < a.revenue.value.units ? -1 : a.orderId.localeCompare(b.orderId)));

  const coverage: CostCoverage = {
    orders: orderCount,
    ordersRead,
    lines,
    linesWithCost,
    percent: lines === 0 ? 0 : Math.round((linesWithCost * 100) / lines),
    complete: entriesComplete && orderCount > 0 && ordersRead === orderCount && lines > 0 && linesWithCost === lines,
  };

  const blockedBy: MarginSummary["blockedBy"] = !entriesComplete
    ? "entries_incomplete"
    : orderCount === 0
      ? "no_orders"
      : ordersRead < orderCount
        ? "orders_not_read"
        : coverage.complete
          ? null
          : "missing_costs";

  // Sin cobertura del 100 % no se agrega NINGUNA magnitud derivada: ni coste ni margen.
  if (!coverage.complete) {
    return {
      coverage,
      margin: null,
      blockedBy,
      revenue: null,
      refunds: null,
      net: null,
      cost: null,
      orders: rows,
      otherCurrencies: [...others].sort(),
      simulated,
    };
  }

  const revenue = rows.reduce((sum, row) => add(sum, row.revenue.value), ZERO);
  const refunds = rows.reduce((sum, row) => add(sum, row.refunds.value), ZERO);
  const cost = rows.reduce((sum, row) => add(sum, row.cost!.value), ZERO);
  const net = subtract(revenue, refunds);
  return {
    coverage,
    margin: declared(subtract(net, cost)),
    blockedBy: null,
    revenue: verified(revenue),
    refunds: verified(refunds),
    net: verified(net),
    cost: declared(cost),
    orders: rows,
    otherCurrencies: [...others].sort(),
    simulated,
  };
}

/** «Costes conocidos: 8 / 10 líneas · Cobertura: 80 %», y lo que falte además de las líneas. */
export function coverageText(coverage: CostCoverage): string {
  if (coverage.orders === 0) return "Ningún pedido con ingreso verificado en este periodo.";
  const unread = coverage.orders - coverage.ordersRead;
  const base = `Costes conocidos: ${coverage.linesWithCost} / ${coverage.lines} líneas · Cobertura: ${coverage.percent} %`;
  if (unread > 0) {
    const plural = unread === 1 ? "pedido no se pudo leer" : "pedidos no se pudieron leer";
    return `${base}. Además, ${unread} ${plural}: su coste es desconocido, no cero.`;
  }
  return base;
}

/** Por qué no hay margen. Nunca se sustituye por un número. */
export const BLOCKED_TEXT: Record<NonNullable<MarginSummary["blockedBy"]>, string> = {
  no_orders: "Ningún pedido con ingreso verificado en euros dentro de este periodo.",
  orders_not_read: "No se pudieron leer todos los pedidos con ingreso verificado: falta coste que no se puede suponer.",
  missing_costs: "Cobertura de costes incompleta: alguna línea de pedido no declara su coste.",
  entries_incomplete: "No se pudieron leer todas las entradas del registro del periodo: el ingreso por pedido estaría incompleto.",
};

/** Texto exacto de un importe (4 decimales), tal como lo entiende el backend. */
export const amountText = (value: Decimal): string => toText(value);

/** Un margen de cero es un cero medido; se distingue de «sin datos», que es `null`. */
export const isMeasuredZero = (value: Decimal) => isZero(value);
