import assert from "node:assert/strict";
import { test } from "node:test";
import { ORDERS_PER_DAY, WINDOW_DAYS } from "./demo/operations.ts";
import {
  ACTIVE_STATUSES,
  buildOrders,
  carrierPerformance,
  daysBetween,
  deliveriesInPeriod,
  incidentList,
  mapView,
  operationalHealth,
  operationsKpis,
  orderDurations,
  orderTimeline,
  ordersInPeriod,
  pipelineStages,
  returnsView,
  startOfDay,
  supplierPerformance,
  type ProductInput,
  type SupplierInput,
} from "./operations-view.ts";

const TODAY = "2026-09-22";

const SUPPLIERS: SupplierInput[] = [
  { id: "sup-cn", name: "Foshan Home Goods Co", region: "china", leadTimeDays: 30, reliability: 0.79, verified: true, isDemo: false },
  { id: "sup-eu", name: "Bratislava Homeware Supply", region: "eu", leadTimeDays: 10, reliability: 0.9, verified: true, isDemo: false },
  { id: "sup-mx", name: "Monterrey Casa Distribution", region: "mexico", leadTimeDays: 14, reliability: 0.48, verified: false, isDemo: true },
];

const PRODUCTS: ProductInput[] = [
  { id: "p1", name: "LED strip lights", sku: "AMZ-HOM-P1", price: 29.9, suppliers: SUPPLIERS },
  { id: "p2", name: "Collapsible laundry basket", sku: "AMZ-HOM-P2", price: 18.5, suppliers: SUPPLIERS.slice(0, 2) },
];

const ORDERS = buildOrders(PRODUCTS, TODAY);

test("buildOrders: determinista, un bloque por día y solo productos y proveedores recibidos", () => {
  assert.equal(ORDERS.length, ORDERS_PER_DAY * WINDOW_DAYS);
  assert.deepEqual(buildOrders(PRODUCTS, TODAY), ORDERS);
  assert.deepEqual(buildOrders([], TODAY), []);
  const ids = new Set(ORDERS.map((o) => o.id));
  assert.equal(ids.size, ORDERS.length);
  for (const order of ORDERS) {
    assert.ok(PRODUCTS.some((p) => p.id === order.productId));
    assert.ok(SUPPLIERS.some((s) => s.id === order.supplierId));
    assert.ok(order.estimatedAt >= order.promisedAt, "la entrega prevista nunca se adelanta a la prometida");
    assert.equal(order.amount, Math.round(PRODUCTS.find((p) => p.id === order.productId)!.price * order.units * 100) / 100);
  }
  // Ordenados del más reciente al más antiguo.
  assert.ok(ORDERS[0].createdAt >= ORDERS[ORDERS.length - 1].createdAt);
  assert.equal(ORDERS[0].createdAt, startOfDay(TODAY));
});

test("buildOrders: el estado sigue a la edad del pedido", () => {
  for (const order of ORDERS) {
    const age = daysBetween(order.createdAt, startOfDay(TODAY));
    const total = daysBetween(order.createdAt, order.estimatedAt);
    if (age === 0) assert.equal(order.status, "confirmed");
    if (age > total) assert.ok(order.status === "delivered" || order.status === "returned", `${order.id} ${order.status}`);
    if (order.status === "returned") assert.ok(order.returnReason && order.returnState);
    if (order.status !== "returned") assert.equal(order.returnReason, null);
  }
});

test("ordersInPeriod: lo que entra, lo que se entrega y lo que sigue abierto", () => {
  const todayOnly = ordersInPeriod(ORDERS, TODAY, 1);
  const active = ORDERS.filter((o) => ACTIVE_STATUSES.includes(o.status));
  assert.ok(todayOnly.length >= ORDERS_PER_DAY + active.length - ORDERS_PER_DAY);
  assert.ok(active.every((o) => todayOnly.includes(o)), "los pedidos abiertos siguen en el periodo");
  assert.ok(todayOnly.every((o) => o.createdAt === startOfDay(TODAY) || ACTIVE_STATUSES.includes(o.status) || o.estimatedAt >= startOfDay(TODAY)));
  assert.ok(ordersInPeriod(ORDERS, TODAY, 7).length >= todayOnly.length);
  assert.equal(ordersInPeriod(ORDERS, TODAY, WINDOW_DAYS).length, ORDERS.length);
});

test("deliveriesInPeriod: solo entregas y devoluciones con fecha dentro de la ventana", () => {
  const today = deliveriesInPeriod(ORDERS, TODAY, 1);
  assert.ok(today.length > 0);
  assert.ok(today.every((o) => (o.status === "delivered" || o.status === "returned") && o.estimatedAt === startOfDay(TODAY)));
  assert.ok(deliveriesInPeriod(ORDERS, TODAY, WINDOW_DAYS).length > today.length);
});

test("pipelineStages: cuenta cada etapa y los activos suman los pedidos abiertos", () => {
  const stages = pipelineStages(ORDERS);
  assert.deepEqual(stages.map((s) => s.key), [...ACTIVE_STATUSES, "delivered"]);
  const active = stages.filter((s) => s.key !== "delivered").reduce((sum, s) => sum + s.count, 0);
  assert.equal(active, ORDERS.filter((o) => ACTIVE_STATUSES.includes(o.status)).length);
  assert.ok(active > 0);
});

test("operationsKpis: tasas entre 0 y 1 y conteos coherentes con los pedidos", () => {
  const kpis = operationsKpis(ORDERS, TODAY, WINDOW_DAYS);
  assert.equal(kpis.inTransit, ORDERS.filter((o) => o.status === "in_transit").length);
  assert.equal(kpis.incidents, ORDERS.filter((o) => o.incident !== null).length);
  for (const rate of [kpis.onTimeRate, kpis.returnRate, kpis.supplierSla]) {
    assert.ok(rate >= 0 && rate <= 1, String(rate));
  }
  assert.ok(kpis.avgDeliveryDays > 0);
  assert.equal(kpis.deliveredTotal, deliveriesInPeriod(ORDERS, TODAY, WINDOW_DAYS).length);
  // Con la ventana de un día las entregas del día siguen midiéndose.
  const todayKpis = operationsKpis(ORDERS, TODAY, 1);
  assert.equal(todayKpis.deliveredToday, deliveriesInPeriod(ORDERS, TODAY, 1).length);
  assert.ok(todayKpis.avgDeliveryDays > 0);
  assert.equal(todayKpis.active, kpis.active);
  const empty = operationsKpis([], TODAY, 1);
  assert.deepEqual([empty.active, empty.onTimeRate, empty.avgDeliveryDays], [0, 0, 0]);
});

test("incidentList: solo pedidos con incidencia, las críticas primero", () => {
  const list = incidentList(ORDERS);
  assert.equal(list.length, ORDERS.filter((o) => o.incident !== null).length);
  const rank = { "Crítica": 0, Alta: 1, Media: 2 } as const;
  for (let k = 1; k < list.length; k++) assert.ok(rank[list[k - 1].severity] <= rank[list[k].severity]);
  assert.ok(list.every((i) => !i.detail.includes("{")), "las plantillas se sustituyen");
});

test("supplierPerformance: un proveedor por cotización con pedidos, ordenado por score", () => {
  const rows = supplierPerformance(ORDERS, SUPPLIERS);
  assert.ok(rows.length > 0 && rows.length <= SUPPLIERS.length);
  assert.equal(rows.reduce((sum, r) => sum + r.orders, 0), ORDERS.length);
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k - 1].score >= rows[k].score);
  assert.ok(rows.every((r) => r.score >= 0 && r.score <= 100));
  assert.equal(rows.find((r) => r.id === "sup-mx")?.isDemo, true);
  assert.deepEqual(supplierPerformance([], SUPPLIERS), []);
});

test("carrierPerformance: solo transportistas con pedidos y puntualidad entre 0 y 1", () => {
  const rows = carrierPerformance(ORDERS);
  assert.ok(rows.length > 0);
  assert.equal(rows.reduce((sum, r) => sum + r.orders, 0), ORDERS.length);
  assert.ok(rows.every((r) => r.onTimeRate >= 0 && r.onTimeRate <= 1 && r.avgDays > 0));
  for (let k = 1; k < rows.length; k++) assert.ok(rows[k - 1].onTimeRate >= rows[k].onTimeRate);
});

test("returnsView: los motivos suman el total de devoluciones", () => {
  const view = returnsView(ORDERS);
  assert.equal(view.total, ORDERS.filter((o) => o.status === "returned").length);
  assert.equal(view.reasons.reduce((sum, r) => sum + r.count, 0), view.total);
  assert.equal(view.states.reduce((sum, s) => sum + s.count, 0), view.total);
  assert.ok(view.rate >= 0 && view.rate <= 1);
});

test("operationalHealth: seis ejes 0–100 y etiqueta según el score", () => {
  const kpis = operationsKpis(ORDERS, TODAY, WINDOW_DAYS);
  const health = operationalHealth(kpis, supplierPerformance(ORDERS, SUPPLIERS), carrierPerformance(ORDERS));
  assert.equal(health.axes.length, 6);
  assert.ok(health.axes.every((a) => a.value >= 0 && a.value <= 100));
  assert.ok(health.score >= 0 && health.score <= 100);
  assert.equal(health.score, Math.round(health.axes.reduce((s, a) => s + a.value, 0) / 6));
  assert.ok(["Excelente", "Buena", "Aceptable", "Requiere atención"].includes(health.label));
});

test("mapView: un nodo por origen y por destino, y rutas entre nodos existentes", () => {
  const { nodes, routes } = mapView(ORDERS);
  assert.ok(nodes.some((n) => n.kind === "origin") && nodes.some((n) => n.kind === "destination"));
  assert.equal(
    nodes.filter((n) => n.kind === "origin").reduce((sum, n) => sum + n.orders, 0),
    ORDERS.length,
  );
  for (const route of routes) {
    assert.ok(nodes.some((n) => n.id === route.from));
    assert.ok(nodes.some((n) => n.id === route.to));
  }
  assert.equal(new Set(routes.map((r) => r.id)).size, routes.length);
  assert.deepEqual(mapView([]), { nodes: [], routes: [] });
});

test("orderTimeline: seis hitos crecientes; el seguimiento real del agente manda", () => {
  const order = ORDERS.find((o) => o.status === "in_transit")!;
  const steps = orderTimeline(order);
  assert.equal(steps.length, 6);
  for (let k = 1; k < steps.length; k++) assert.ok(steps[k].at >= steps[k - 1].at);
  assert.equal(steps.filter((s) => s.current).length, 1);
  assert.equal(steps[0].at, order.createdAt);

  const withRecord = orderTimeline(order, {
    correlation_id: "c",
    product_id: order.productId,
    marketing_campaign_id: null,
    market: order.market,
    operations_status: "READY",
    recommendation: "GO",
    confidence: 0.8,
    data: {
      order: {
        order_id: "ORD-1",
        quantity: 1,
        tracking: {
          stages: [
            { stage: "order_placed", day_offset: 0 },
            { stage: "processing", day_offset: 1 },
            { stage: "shipped", day_offset: 10 },
            { stage: "out_for_delivery", day_offset: 12 },
            { stage: "delivered", day_offset: 13 },
          ],
          lead_time_days_used: 10,
        },
      },
    },
  });
  assert.equal(daysBetween(order.createdAt, withRecord.find((s) => s.key === "picked_up")!.at), 10);
  assert.equal(daysBetween(order.createdAt, withRecord.at(-1)!.at), 13);

  const durations = orderDurations(withRecord);
  assert.ok(durations.processing > 0 && durations.pickup > 0 && durations.transit > 0);
});
