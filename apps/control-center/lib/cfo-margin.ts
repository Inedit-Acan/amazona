import type { Order, RevenueEntry } from "./api.ts";
import { add, isZero, multiplyByCount, parseDecimal, subtract, toText, ZERO, type Decimal } from "./decimal.ts";
import {
  addVerified,
  declared,
  isOrigin,
  subtractVerified,
  verified,
  type Declared,
  type Origin,
  type Verified,
} from "./provenance.ts";

// Coste declarado y margen de contribución declarado (M45, Commit 10), POR ORIGEN (M46, Commit 4, ADR 0031 A6).
//
//   margen de contribución declarado = ingreso verificado − reembolsos verificados − coste declarado del pedido
//
// Las dos primeras magnitudes son HECHOS del registro (ADR 0030) y cada uno es de UN origen (`provider_kind`: mock,
// sandbox o real). La tercera es un dato DECLARADO: el backend guarda `unit_cost` de cada línea con su
// `cost_provenance` (`supplier_quote` o `declared`) y su `cost_source`, y lo deja en `null` cuando nadie lo ha dicho — un
// coste desconocido no es un coste cero.
//
// Por eso el resultado se etiqueta **declarado**, nunca verificado: una cifra no puede ser más fiable que el menos
// fiable de sus ingredientes. Y por eso sólo existe cuando:
//
//   1. el pedido está en la moneda contable (EUR, D3 del ADR 0030): aquí no se convierte ninguna divisa;
//   2. TODAS sus líneas tienen `unit_cost` conocido;
//   3. ese coste trae su procedencia declarada;
//   4. el pedido tiene ingreso de UN solo origen: el coste es del pedido, no de un origen, y repartirlo entre varios
//      sería inventar un reparto. Un pedido con ingreso en varios orígenes enseña sus cifras separadas por origen y no
//      tiene margen, ni el de ninguno de los orígenes implicados;
//   5. no falta ninguna magnitud necesaria (ni un pedido que no se haya podido leer).
//
// El margen se agrega POR ORIGEN: no existe nunca un margen que cruce orígenes (ni suma, ni promedio, ni reparto). Si
// falta cualquier coste, el margen de ese origen es `null` y la pantalla dice «Cobertura de costes incompleta». Nunca
// se estima, nunca se asume cero, nunca se completa con constantes y nunca se llama beneficio. Nada de aquí lee
// `Order.is_simulated`: el origen del dinero sale del `provider_kind` de las entradas del registro, y nada más.

/** La única moneda que se consolida (D3 del ADR 0030). Lo demás se enseña aparte y no se convierte. */
export const ACCOUNTING_CURRENCY = "EUR";

/** Lo verificado del registro es sólo `ORDER_PAYMENT`; un duplicado o una discrepancia nunca entra aquí. */
const VERIFIED_CLASSIFICATION = "ORDER_PAYMENT";

/** Un pedido en un origen. Si el pedido tiene ingreso en varios orígenes, aparece una fila por cada uno. */
export interface OrderMargin {
  orderId: string;
  origin: Origin;
  currency: string;
  revenue: Verified<Decimal, Origin>;
  refunds: Verified<Decimal, Origin>;
  net: Verified<Decimal, Origin>;
  /** Todos los orígenes con ingreso verificado en este pedido. Más de uno ⇒ no hay margen (el coste es del pedido). */
  orderOrigins: Origin[];
  /** El pedido se pudo leer. Uno que no se leyó es coste desconocido, no coste cero. */
  read: boolean;
  /** Coste declarado del pedido; `null` = alguna línea no tiene coste conocido. */
  cost: Declared<Decimal> | null;
  /** Margen de contribución declarado; `null` con coste desconocido o con ingreso en varios orígenes. */
  margin: Declared<Decimal> | null;
  lines: number;
  linesWithCost: number;
  /** Las procedencias distintas del coste de las líneas (`supplier_quote`, `declared`…). */
  costProvenances: string[];
}

export interface CostCoverage {
  /** Pedidos con ingreso verificado en este origen y en la moneda contable dentro del periodo. */
  orders: number;
  /** De ésos, cuántos se pudieron leer. Un pedido que no se leyó es coste desconocido, no coste cero. */
  ordersRead: number;
  lines: number;
  linesWithCost: number;
  /** Porcentaje de líneas con coste conocido, sobre los pedidos leídos (0 si no hay ninguna línea). */
  percent: number;
  /** Todo lo necesario está: se puede agregar un margen de este origen. */
  complete: boolean;
}

export type MarginBlock =
  | "no_orders"
  | "orders_not_read"
  | "missing_costs"
  | "entries_incomplete"
  | "mixed_origins"
  | "unknown_origin";

/** El margen de UN origen. */
export interface OriginMargin {
  origin: Origin;
  coverage: CostCoverage;
  /** Margen de contribución declarado de este origen. **Sólo existe con cobertura del 100 %.** */
  margin: Declared<Decimal> | null;
  /** Por qué no hay margen de este origen, cuando no lo hay. */
  blockedBy: MarginBlock | null;
  revenue: Verified<Decimal, Origin> | null;
  refunds: Verified<Decimal, Origin> | null;
  net: Verified<Decimal, Origin> | null;
  cost: Declared<Decimal> | null;
  /** Filas de este origen, del pedido de más ingreso al de menos (de ESTE origen). */
  orders: OrderMargin[];
}

export interface MarginSummary {
  /** Un elemento por origen con ingreso verificado en EUR; vacío = «Sin datos». Nunca hay un elemento que sume orígenes. */
  origins: OriginMargin[];
  /** Por qué no hay nada que enseñar, cuando `origins` está vacío. */
  blockedBy: "no_orders" | "entries_incomplete" | "unknown_origin" | null;
  /** Pedidos con ingreso verificado en otra moneda: se enseñan aparte y no se suman ni se convierten. */
  otherCurrencies: string[];
  /** Pedidos con una entrada cuyo origen no es del vocabulario: no se asignan a ningún origen y bloquean todos. */
  unknownOrigin: number;
}

interface OriginTotals {
  revenue: Decimal;
  refunds: Decimal;
}

interface Totals {
  currency: string;
  byOrigin: Map<Origin, OriginTotals>;
  /** Alguna entrada trajo un origen que no es mock, sandbox ni real. */
  unknownOrigin: boolean;
}

/** Ingreso y reembolso **verificados** por pedido Y POR ORIGEN, a partir de las entradas del registro. */
function byOrder(entries: RevenueEntry[]): Map<string, Totals> {
  const totals = new Map<string, Totals>();
  for (const entry of entries) {
    if (entry.classification !== VERIFIED_CLASSIFICATION) continue;
    const amount = parseDecimal(entry.amount);
    if (amount === null) continue; // un importe que no es decimal no se adivina: no entra
    const current = totals.get(entry.order_id) ?? { currency: entry.currency, byOrigin: new Map(), unknownOrigin: false };
    // Un pedido con entradas en dos monedas no es agregable: se marca y se descarta más abajo.
    current.currency = current.currency === entry.currency ? current.currency : "";
    const origin: unknown = entry.provider_kind;
    if (!isOrigin(origin)) {
      current.unknownOrigin = true; // un origen ausente o desconocido no se completa jamás
    } else {
      const cell = current.byOrigin.get(origin) ?? { revenue: ZERO, refunds: ZERO };
      current.byOrigin.set(origin, {
        revenue: entry.kind === "CAPTURE" ? add(cell.revenue, amount) : cell.revenue,
        refunds: entry.kind === "REFUND" ? add(cell.refunds, amount) : cell.refunds,
      });
    }
    totals.set(entry.order_id, current);
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

const byRevenueThenId = (a: OrderMargin, b: OrderMargin) =>
  b.revenue.value.units > a.revenue.value.units
    ? 1
    : b.revenue.value.units < a.revenue.value.units
      ? -1
      : a.orderId.localeCompare(b.orderId);

/** El margen de contribución declarado del periodo, POR ORIGEN, y por qué no existe cuando no existe.
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

  const rowsByOrigin = new Map<Origin, OrderMargin[]>();
  const others = new Set<string>();
  let unknownOrigin = 0;

  for (const [orderId, total] of totals) {
    if (total.currency !== ACCOUNTING_CURRENCY) {
      if (total.currency !== "") others.add(total.currency);
      continue; // otra moneda (o varias): fuera del agregado, nunca convertida
    }
    if (total.unknownOrigin) {
      unknownOrigin += 1; // no se asigna a ningún origen
      continue;
    }
    const order = known.get(orderId);
    const cost = order === undefined ? null : declaredCost(order);
    const orderOrigins = [...total.byOrigin.keys()].sort();
    for (const origin of orderOrigins) {
      const cell = total.byOrigin.get(origin)!;
      const revenue = verified(cell.revenue, origin);
      const refunds = verified(cell.refunds, origin);
      const net = subtractVerified(revenue, refunds);
      const single = orderOrigins.length === 1;
      const rows = rowsByOrigin.get(origin) ?? [];
      rows.push({
        orderId,
        origin,
        currency: total.currency,
        revenue,
        refunds,
        net,
        orderOrigins,
        read: order !== undefined,
        cost: cost === null || cost.cost === null ? null : declared(cost.cost),
        // La única combinación que cruza procedencias, y degrada a «declarado». Sin margen si el pedido es de varios
        // orígenes: el coste es del pedido y no se reparte.
        margin: single && cost !== null && cost.cost !== null ? declared(subtract(net.value, cost.cost)) : null,
        lines: cost === null ? 0 : cost.lines,
        linesWithCost: cost === null ? 0 : cost.withCost,
        costProvenances: cost === null ? [] : cost.provenances,
      });
      rowsByOrigin.set(origin, rows);
    }
  }

  const origins: OriginMargin[] = [...rowsByOrigin.keys()].sort().map((origin) => {
    const rows = rowsByOrigin.get(origin)!.sort(byRevenueThenId);
    return originMargin(origin, rows, { entriesComplete, unknownOrigin });
  });

  const blockedBy: MarginSummary["blockedBy"] =
    origins.length > 0
      ? null
      : !entriesComplete
        ? "entries_incomplete"
        : unknownOrigin > 0
          ? "unknown_origin"
          : "no_orders";

  return { origins, blockedBy, otherCurrencies: [...others].sort(), unknownOrigin };
}

function originMargin(
  origin: Origin,
  rows: OrderMargin[],
  { entriesComplete, unknownOrigin }: { entriesComplete: boolean; unknownOrigin: number },
): OriginMargin {
  const ordersRead = rows.filter((row) => row.read).length;
  const lines = rows.reduce((sum, row) => sum + row.lines, 0);
  const linesWithCost = rows.reduce((sum, row) => sum + row.linesWithCost, 0);
  const mixed = rows.some((row) => row.orderOrigins.length > 1);
  const costsComplete = ordersRead === rows.length && lines > 0 && linesWithCost === lines;
  const complete = entriesComplete && unknownOrigin === 0 && rows.length > 0 && !mixed && costsComplete;
  const coverage: CostCoverage = {
    orders: rows.length,
    ordersRead,
    lines,
    linesWithCost,
    percent: lines === 0 ? 0 : Math.round((linesWithCost * 100) / lines),
    complete,
  };

  const blockedBy: MarginBlock | null = !entriesComplete
    ? "entries_incomplete"
    : unknownOrigin > 0
      ? "unknown_origin"
      : rows.length === 0
        ? "no_orders"
        : ordersRead < rows.length
          ? "orders_not_read"
          : mixed
            ? "mixed_origins"
            : complete
              ? null
              : "missing_costs";

  // Sin cobertura del 100 % no se agrega NINGUNA magnitud derivada de este origen: ni coste ni margen.
  if (!complete) {
    return { origin, coverage, margin: null, blockedBy, revenue: null, refunds: null, net: null, cost: null, orders: rows };
  }

  // Todas las filas son de este origen: addVerified lo exige y lanzaría si alguna no lo fuera.
  const zero = verified(ZERO, origin);
  const revenue = rows.reduce((sum, row) => addVerified(sum, row.revenue), zero);
  const refunds = rows.reduce((sum, row) => addVerified(sum, row.refunds), zero);
  const cost = rows.reduce((sum, row) => add(sum, row.cost!.value), ZERO);
  const net = subtractVerified(revenue, refunds);
  return {
    origin,
    coverage,
    margin: declared(subtract(net.value, cost)),
    blockedBy: null,
    revenue,
    refunds,
    net,
    cost: declared(cost),
    orders: rows,
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
export const BLOCKED_TEXT: Record<MarginBlock, string> = {
  no_orders: "Ningún pedido con ingreso verificado en euros dentro de este periodo.",
  orders_not_read: "No se pudieron leer todos los pedidos con ingreso verificado: falta coste que no se puede suponer.",
  missing_costs: "Cobertura de costes incompleta: alguna línea de pedido no declara su coste.",
  entries_incomplete: "No se pudieron leer todas las entradas del registro del periodo: el ingreso por pedido estaría incompleto.",
  mixed_origins:
    "Algún pedido tiene ingreso de varios orígenes: su coste es del pedido y no se reparte entre orígenes, así que este origen no tiene margen.",
  unknown_origin: "Alguna entrada del registro trae un origen que no se reconoce: no se asigna a ningún origen y bloquea el margen.",
};

/** Texto exacto de un importe (4 decimales), tal como lo entiende el backend. */
export const amountText = (value: Decimal): string => toText(value);

/** Un margen de cero es un cero medido; se distingue de «sin datos», que es `null`. */
export const isMeasuredZero = (value: Decimal) => isZero(value);
