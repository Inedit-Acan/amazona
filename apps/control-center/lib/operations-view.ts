import type { OperationsRecord } from "./api.ts";
import {
  DEMO_CARRIERS,
  DEMO_CHANNELS,
  DEMO_CUSTOMERS,
  DEMO_DEFECT_RANGE,
  DEMO_INCIDENT_RATE,
  DEMO_INCIDENT_TYPES,
  DEMO_MARKETS,
  DEMO_RETURN_RATE,
  DEMO_RETURN_REASONS,
  DEMO_RETURN_STATES,
  DEMO_TRANSIT_DAYS,
  ORDERS_PER_DAY,
  WINDOW_DAYS,
  type IncidentKind,
} from "./demo/operations.ts";
import { demoRandom } from "./demo/random.ts";
import { REGION_ANCHORS, regionLabel } from "./regions.ts";

// Vista de la pantalla de Operaciones (mockup docs/design/operaciones.png).
// AMAZONA no recibe pedidos reales: los pedidos, incidencias, devoluciones y
// transportistas son de demostración (lib/demo/operations.ts), pero se generan
// sobre datos reales —productos, cotizaciones del proveedor (origen, plazo,
// fiabilidad) y precio del análisis económico— y de forma determinista, así que
// el panel es coherente con Proveedores, Economía y Tienda. El informe del
// agente de operaciones, cuando existe, manda en el seguimiento del pedido.

const DAY_MS = 86_400_000;

export interface SupplierInput {
  id: string;
  name: string;
  region: string;
  leadTimeDays: number;
  reliability: number;
  verified: boolean;
  /** No hay cotización real del producto: el proveedor también es de demostración. */
  isDemo: boolean;
}

export interface ProductInput {
  id: string;
  name: string;
  sku: string;
  price: number;
  suppliers: SupplierInput[];
}

export type OrderStatus = "confirmed" | "supplier" | "preparing" | "shipped" | "in_transit" | "delivered" | "returned";

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  confirmed: "Confirmado",
  supplier: "Proveedor",
  preparing: "Preparación",
  shipped: "Despachado",
  in_transit: "En tránsito",
  delivered: "Entregado",
  returned: "Devuelto",
};

export type SlaState = "ok" | "risk" | "breach";
export type RiskLevel = "Bajo" | "Medio" | "Alto";

export interface Order {
  id: string;
  /** Día del pedido (epoch UTC a medianoche). */
  createdAt: number;
  /** Entrega prometida y entrega real o prevista (epoch UTC). */
  promisedAt: number;
  estimatedAt: number;
  channel: string;
  productId: string;
  productName: string;
  sku: string;
  customer: string;
  supplierId: string;
  supplierName: string;
  supplierRegion: string;
  supplierReliability: number;
  carrier: string;
  market: string;
  units: number;
  amount: number;
  status: OrderStatus;
  sla: SlaState;
  risk: RiskLevel;
  incident: IncidentKind | null;
  returnReason: string | null;
  returnState: string | null;
  /** El proveedor confirmó dentro de su SLA (24 h). */
  supplierOnTime: boolean;
  isDemo: true;
}

/** Medianoche UTC del día de `iso` (YYYY-MM-DD o ISO completo). */
export function startOfDay(iso: string): number {
  return Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
}

function pick<T>(list: T[], value: number): T {
  return list[Math.min(list.length - 1, Math.floor(value * list.length))];
}

function pickWeighted<T extends { weight: number }>(list: T[], value: number): T {
  const total = list.reduce((sum, item) => sum + item.weight, 0);
  let acc = 0;
  for (const item of list) {
    acc += item.weight / total;
    if (value <= acc) return item;
  }
  return list[list.length - 1];
}

/** Días naturales transcurridos entre dos instantes. */
export function daysBetween(from: number, to: number): number {
  return Math.round((to - from) / DAY_MS);
}

/** Pedidos de la ventana de demostración: ORDERS_PER_DAY por día durante
 * WINDOW_DAYS, deterministas por (día, índice) y repartidos entre los productos
 * reales y sus proveedores. */
export function buildOrders(products: ProductInput[], today: string): Order[] {
  if (products.length === 0) return [];
  const todayStart = startOfDay(today);
  const orders: Order[] = [];
  let sequence = 2000;

  for (let age = WINDOW_DAYS - 1; age >= 0; age--) {
    for (let k = 0; k < ORDERS_PER_DAY; k++) {
      const seed = `order-${age}-${k}`;
      const r = (salt: string) => demoRandom(seed, salt);
      const product = pick(products, r("product"));
      if (product.suppliers.length === 0) continue;
      const supplier = pick(product.suppliers, r("supplier"));
      const carriers = DEMO_CARRIERS.filter((c) => c.regions.includes(supplier.region));
      const carrier = pick(carriers.length ? carriers : DEMO_CARRIERS, r("carrier"));
      const market = pickWeighted(DEMO_MARKETS, r("market"));
      const transit = DEMO_TRANSIT_DAYS[supplier.region] ?? 5;
      const promisedDays = Math.max(2, Math.round((transit + carrier.avgDays) / 2) + 1);
      // Retraso: la fiabilidad del proveedor y la puntualidad del transportista mandan.
      const punctuality = (supplier.reliability + carrier.onTime) / 2;
      const delayRoll = r("delay");
      const delayDays = delayRoll > punctuality ? 1 + Math.floor(r("delay-size") * 3) : 0;
      const actualDays = promisedDays + delayDays;
      const createdAt = todayStart - age * DAY_MS;

      const t = (share: number) => actualDays * share;
      let status: OrderStatus =
        age < t(0.15)
          ? "confirmed"
          : age < t(0.3)
            ? "supplier"
            : age < t(0.5)
              ? "preparing"
              : age < t(0.65)
                ? "shipped"
                : age < actualDays
                  ? "in_transit"
                  : "delivered";

      const returned = status === "delivered" && age >= actualDays + 2 && r("return") < DEMO_RETURN_RATE;
      if (returned) status = "returned";

      const active = status !== "delivered" && status !== "returned";
      const incidentRoll = r("incident");
      const incident: IncidentKind | null = active && incidentRoll < DEMO_INCIDENT_RATE ? incidentKind(status, supplier.region, r("incident-kind")) : null;
      const sla: SlaState = delayDays >= 2 || incident === "supplier_unconfirmed" ? "breach" : delayDays === 1 || incident ? "risk" : "ok";
      const risk: RiskLevel = sla === "breach" ? "Alto" : sla === "risk" || supplier.reliability < 0.6 ? "Medio" : "Bajo";
      const units = 1 + Math.floor(r("units") * 3);

      orders.push({
        id: `AMZ-0${sequence++}`,
        createdAt,
        promisedAt: createdAt + promisedDays * DAY_MS,
        estimatedAt: createdAt + actualDays * DAY_MS,
        channel: pick(DEMO_CHANNELS, r("channel")),
        productId: product.id,
        productName: product.name,
        sku: product.sku,
        customer: pick(DEMO_CUSTOMERS, r("customer")),
        supplierId: supplier.id,
        supplierName: supplier.name,
        supplierRegion: supplier.region,
        supplierReliability: supplier.reliability,
        carrier: carrier.name,
        market: market.value,
        units,
        amount: Math.round(product.price * units * 100) / 100,
        status,
        sla,
        risk,
        incident,
        returnReason: returned ? pickWeighted(DEMO_RETURN_REASONS.map((x) => ({ ...x, weight: x.share })), r("return-reason")).label : null,
        returnState: returned ? pickWeighted(DEMO_RETURN_STATES.map((x) => ({ ...x, weight: x.share })), r("return-state")).label : null,
        supplierOnTime: r("supplier-sla") < supplier.reliability + 0.08,
        isDemo: true,
      });
    }
  }
  return orders.sort((a, b) => b.createdAt - a.createdAt || a.id.localeCompare(b.id));
}

function incidentKind(status: OrderStatus, region: string, value: number): IncidentKind {
  if (status === "confirmed" || status === "supplier") return "supplier_unconfirmed";
  if (status === "preparing") return "address_change";
  if (region !== "eu" && value < 0.5) return "customs_hold";
  return value < 0.75 ? "tracking_stalled" : "damaged";
}

export const ACTIVE_STATUSES: OrderStatus[] = ["confirmed", "supplier", "preparing", "shipped", "in_transit"];

/** Pedidos con actividad en la ventana de `days` días que termina hoy: los que
 * entraron en ella, los que se entregaron en ella y los que siguen abiertos (un
 * pedido en tránsito de hace dos semanas sigue siendo trabajo de hoy). */
export function ordersInPeriod(orders: Order[], today: string, days: number): Order[] {
  const from = startOfDay(today) - (days - 1) * DAY_MS;
  const to = startOfDay(today) + DAY_MS;
  return orders.filter(
    (o) => o.createdAt >= from || ACTIVE_STATUSES.includes(o.status) || (o.estimatedAt >= from && o.estimatedAt < to),
  );
}

/** Entregas (o devoluciones) ocurridas dentro de la ventana. */
export function deliveriesInPeriod(orders: Order[], today: string, days: number): Order[] {
  const from = startOfDay(today) - (days - 1) * DAY_MS;
  const to = startOfDay(today) + DAY_MS;
  return orders.filter((o) => (o.status === "delivered" || o.status === "returned") && o.estimatedAt >= from && o.estimatedAt < to);
}

export interface PipelineStage {
  key: OrderStatus;
  label: string;
  count: number;
}

/** Estado actual de los pedidos activos, etapa a etapa. */
export function pipelineStages(orders: Order[]): PipelineStage[] {
  return [...ACTIVE_STATUSES, "delivered" as const].map((key) => ({
    key,
    label: ORDER_STATUS_LABEL[key],
    count: orders.filter((o) => o.status === key).length,
  }));
}

export interface OperationsKpis {
  active: number;
  inTransit: number;
  deliveredToday: number;
  /** Fracciones. */
  onTimeRate: number;
  returnRate: number;
  supplierSla: number;
  incidents: number;
  avgDeliveryDays: number;
  deliveredTotal: number;
}

/** KPIs de la cabecera. Los de estado (activos, en tránsito, incidencias) son una
 * foto de ahora; los de calidad (a tiempo, devoluciones, entrega media) se miden
 * sobre las entregas del periodo, y el SLA del proveedor sobre lo que entró en él. */
export function operationsKpis(orders: Order[], today: string, days: number): OperationsKpis {
  const todayStart = startOfDay(today);
  const from = todayStart - (days - 1) * DAY_MS;
  const delivered = deliveriesInPeriod(orders, today, days);
  const entered = orders.filter((o) => o.createdAt >= from);
  const onTime = delivered.filter((o) => o.estimatedAt <= o.promisedAt).length;
  const returned = delivered.filter((o) => o.status === "returned").length;
  const deliveryDays = delivered.map((o) => daysBetween(o.createdAt, o.estimatedAt));
  const slaBase = entered.length ? entered : orders;
  return {
    active: orders.filter((o) => ACTIVE_STATUSES.includes(o.status)).length,
    inTransit: orders.filter((o) => o.status === "in_transit").length,
    deliveredToday: delivered.filter((o) => o.estimatedAt >= todayStart && o.estimatedAt < todayStart + DAY_MS).length,
    onTimeRate: delivered.length ? onTime / delivered.length : 0,
    returnRate: delivered.length ? returned / delivered.length : 0,
    supplierSla: slaBase.length ? slaBase.filter((o) => o.supplierOnTime).length / slaBase.length : 0,
    incidents: orders.filter((o) => o.incident !== null).length,
    avgDeliveryDays: deliveryDays.length ? deliveryDays.reduce((sum, d) => sum + d, 0) / deliveryDays.length : 0,
    deliveredTotal: delivered.length,
  };
}

export interface IncidentView {
  order: Order;
  kind: IncidentKind;
  severity: "Crítica" | "Alta" | "Media";
  title: string;
  detail: string;
  action: string;
  hours: number;
}

const SEVERITY_ORDER = { Crítica: 0, Alta: 1, Media: 2 };

/** Incidencias abiertas, de la más grave a la más leve. */
export function incidentList(orders: Order[]): IncidentView[] {
  return orders
    .filter((o) => o.incident !== null)
    .map((order) => {
      const type = DEMO_INCIDENT_TYPES.find((t) => t.kind === order.incident)!;
      return {
        order,
        kind: type.kind,
        severity: type.severity,
        title: type.title,
        detail: type.detail.replace("{carrier}", order.carrier).replace("{origin}", regionLabel(order.supplierRegion)).replace("{hours}", String(type.hours)),
        action: type.action,
        hours: type.hours,
      };
    })
    .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || b.order.createdAt - a.order.createdAt);
}

export interface SupplierPerformanceRow {
  id: string;
  name: string;
  region: string;
  orders: number;
  onTimeRate: number;
  defectRate: number;
  /** 0–100. */
  score: number;
  isDemo: boolean;
}

/** Rendimiento por proveedor: los pedidos y la puntualidad salen de los pedidos
 * generados; la fiabilidad y el origen, de la cotización real cuando existe. */
export function supplierPerformance(orders: Order[], suppliers: SupplierInput[]): SupplierPerformanceRow[] {
  return suppliers
    .map((supplier) => {
      const own = orders.filter((o) => o.supplierId === supplier.id);
      const finished = own.filter((o) => o.status === "delivered" || o.status === "returned");
      const onTimeRate = finished.length ? finished.filter((o) => o.estimatedAt <= o.promisedAt).length / finished.length : supplier.reliability;
      const defectRate = DEMO_DEFECT_RANGE.min + demoRandom(supplier.id, "defects") * (DEMO_DEFECT_RANGE.max - DEMO_DEFECT_RANGE.min);
      const score = Math.round((onTimeRate * 0.5 + supplier.reliability * 0.35 + (1 - defectRate / DEMO_DEFECT_RANGE.max) * 0.15) * 100);
      return {
        id: supplier.id,
        name: supplier.name,
        region: supplier.region,
        orders: own.length,
        onTimeRate,
        defectRate,
        score,
        isDemo: supplier.isDemo,
      };
    })
    .filter((row) => row.orders > 0)
    .sort((a, b) => b.score - a.score || b.orders - a.orders);
}

export interface CarrierRow {
  name: string;
  orders: number;
  onTimeRate: number;
  avgDays: number;
}

/** Rendimiento por transportista sobre los pedidos del periodo. */
export function carrierPerformance(orders: Order[]): CarrierRow[] {
  return DEMO_CARRIERS.map((carrier) => {
    const own = orders.filter((o) => o.carrier === carrier.name);
    const finished = own.filter((o) => o.status === "delivered" || o.status === "returned");
    const days = finished.map((o) => daysBetween(o.createdAt, o.estimatedAt));
    return {
      name: carrier.name,
      orders: own.length,
      onTimeRate: finished.length ? finished.filter((o) => o.estimatedAt <= o.promisedAt).length / finished.length : carrier.onTime,
      avgDays: days.length ? days.reduce((sum, d) => sum + d, 0) / days.length : carrier.avgDays,
    };
  })
    .filter((row) => row.orders > 0)
    .sort((a, b) => b.onTimeRate - a.onTimeRate);
}

export interface ReturnsView {
  rate: number;
  total: number;
  states: { key: string; label: string; count: number }[];
  reasons: { label: string; share: number; count: number }[];
}

/** Devoluciones del periodo: tasa, estado y motivos. */
export function returnsView(orders: Order[]): ReturnsView {
  const returned = orders.filter((o) => o.status === "returned");
  const delivered = orders.filter((o) => o.status === "delivered" || o.status === "returned");
  const counted = (predicate: (o: Order) => boolean) => returned.filter(predicate).length;
  return {
    rate: delivered.length ? returned.length / delivered.length : 0,
    total: returned.length,
    states: DEMO_RETURN_STATES.map((state) => ({ key: state.key, label: state.label, count: counted((o) => o.returnState === state.label) })),
    reasons: DEMO_RETURN_REASONS.map((reason) => {
      const count = counted((o) => o.returnReason === reason.label);
      return { label: reason.label, share: returned.length ? count / returned.length : reason.share, count };
    }).sort((a, b) => b.share - a.share),
  };
}

export interface HealthAxis {
  label: string;
  /** 0–100. */
  value: number;
}

/** Operational Health: media de seis ejes derivados de los KPIs del periodo. */
export function operationalHealth(kpis: OperationsKpis, suppliers: SupplierPerformanceRow[], carriers: CarrierRow[]): { score: number; label: string; axes: HealthAxis[] } {
  const clamp = (value: number) => Math.max(0, Math.min(100, Math.round(value)));
  const supplierScore = suppliers.length ? suppliers.reduce((sum, s) => sum + s.score, 0) / suppliers.length : 0;
  const carrierScore = carriers.length ? (carriers.reduce((sum, c) => sum + c.onTimeRate, 0) / carriers.length) * 100 : 0;
  const axes: HealthAxis[] = [
    { label: "Pedidos", value: clamp(100 - (kpis.active ? (kpis.incidents / kpis.active) * 100 * 3 : 0)) },
    { label: "Proveedores", value: clamp(supplierScore) },
    { label: "Logística", value: clamp(carrierScore) },
    { label: "Entregas", value: clamp(kpis.onTimeRate * 100) },
    { label: "Devoluciones", value: clamp(100 - kpis.returnRate * 100 * 2) },
    { label: "Incidencias", value: clamp(100 - kpis.incidents * 2) },
  ];
  const score = Math.round(axes.reduce((sum, a) => sum + a.value, 0) / axes.length);
  return { score, label: score >= 90 ? "Excelente" : score >= 75 ? "Buena" : score >= 60 ? "Aceptable" : "Requiere atención", axes };
}

export interface MapNode {
  id: string;
  label: string;
  lonLat: [number, number];
  kind: "origin" | "destination";
  orders: number;
  avgDays: number;
  tone: "ok" | "warn" | "bad";
}

/** Mapa logístico: un nodo por región de proveedor y por mercado de destino,
 * con los pedidos del periodo y su tiempo medio. */
export function mapView(orders: Order[]): { nodes: MapNode[]; routes: { id: string; from: string; to: string }[] } {
  const nodes: MapNode[] = [];
  const average = (list: Order[]) => (list.length ? list.reduce((sum, o) => sum + daysBetween(o.createdAt, o.estimatedAt), 0) / list.length : 0);
  const tone = (list: Order[]): "ok" | "warn" | "bad" => {
    if (list.length === 0) return "ok";
    if (list.filter((o) => o.incident !== null).length / list.length > 0.03) return "bad";
    return list.filter((o) => o.sla !== "ok").length / list.length > 0.15 ? "warn" : "ok";
  };

  for (const region of Object.keys(REGION_ANCHORS)) {
    const own = orders.filter((o) => o.supplierRegion === region);
    if (own.length === 0) continue;
    nodes.push({
      id: `origin-${region}`,
      label: regionLabel(region),
      lonLat: REGION_ANCHORS[region],
      kind: "origin",
      orders: own.length,
      avgDays: average(own),
      tone: tone(own),
    });
  }
  for (const market of DEMO_MARKETS) {
    const own = orders.filter((o) => o.market === market.value);
    if (own.length === 0) continue;
    nodes.push({
      id: `market-${market.value}`,
      label: market.label,
      lonLat: market.lonLat,
      kind: "destination",
      orders: own.length,
      avgDays: average(own),
      tone: tone(own),
    });
  }

  const routes = new Map<string, { id: string; from: string; to: string }>();
  for (const order of orders) {
    const from = `origin-${order.supplierRegion}`;
    const to = `market-${order.market}`;
    const id = `${from}-${to}`;
    if (!routes.has(id) && nodes.some((n) => n.id === from) && nodes.some((n) => n.id === to)) routes.set(id, { id, from, to });
  }
  return { nodes, routes: [...routes.values()] };
}

export interface TimelineStep {
  key: string;
  label: string;
  at: number;
  done: boolean;
  current: boolean;
}

const TIMELINE: { key: string; label: string; share: number; status: OrderStatus }[] = [
  { key: "order_placed", label: "Pedido realizado", share: 0, status: "confirmed" },
  { key: "supplier_accepted", label: "Proveedor acepta", share: 0.15, status: "supplier" },
  { key: "processing", label: "Preparado", share: 0.3, status: "preparing" },
  { key: "picked_up", label: "Recogido transportista", share: 0.5, status: "shipped" },
  { key: "in_transit", label: "En tránsito", share: 0.65, status: "in_transit" },
  { key: "delivered", label: "Entrega estimada", share: 1, status: "delivered" },
];

const STATUS_RANK: Record<OrderStatus, number> = {
  confirmed: 0,
  supplier: 1,
  preparing: 2,
  shipped: 3,
  in_transit: 4,
  delivered: 5,
  returned: 6,
};

/** Hitos del pedido. Si el agente de operaciones guardó un seguimiento real para
 * ese producto y mercado, sus `day_offset` mandan sobre los de la demo. */
export function orderTimeline(order: Order, record?: OperationsRecord): TimelineStep[] {
  const stages = record?.data?.order?.tracking?.stages ?? [];
  const total = daysBetween(order.createdAt, order.estimatedAt);
  const realOffset = (key: string) => {
    const map: Record<string, string> = {
      order_placed: "order_placed",
      supplier_accepted: "processing",
      processing: "processing",
      picked_up: "shipped",
      in_transit: "out_for_delivery",
      delivered: "delivered",
    };
    return stages.find((s) => s.stage === map[key])?.day_offset;
  };
  const rank = STATUS_RANK[order.status === "returned" ? "delivered" : order.status];
  return TIMELINE.map((step) => {
    const offset = realOffset(step.key) ?? total * step.share;
    const stepRank = STATUS_RANK[step.status];
    return {
      key: step.key,
      label: step.label,
      at: order.createdAt + offset * DAY_MS,
      done: stepRank < rank,
      current: stepRank === rank,
    };
  });
}

/** Reparto del tiempo del pedido entre procesamiento, recogida y tránsito. */
export function orderDurations(steps: TimelineStep[]): { processing: number; pickup: number; transit: number } {
  const at = (key: string) => steps.find((s) => s.key === key)?.at ?? 0;
  return {
    processing: at("supplier_accepted") - at("order_placed"),
    pickup: at("picked_up") - at("supplier_accepted"),
    transit: at("delivered") - at("picked_up"),
  };
}
