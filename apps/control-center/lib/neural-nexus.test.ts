import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution, AgentRelation, Task } from "./api.ts";
import { readAgentStatus } from "./agent-status.ts";
import { CEO_ANCHOR, zoneAnchor } from "./decision-engine.ts";
import { DOMAINS } from "./nexus-domains.ts";
import {
  CEO_ID,
  CORE_ID,
  LAYOUT,
  agentAngle,
  agentSlots,
  applyMode,
  buildGraph,
  domainAngle,
  meanLatencyMs,
  neuralZones,
  nodeStatusOfRegistry,
  relatedIds,
  ringPosition,
  worstStatus,
  type GraphNode,
} from "./neural-nexus.ts";
import { task } from "./nexus-test-support.ts";

const NOW = Date.UTC(2026, 8, 24, 12, 0, 0);

const agent = (id: string, name: string, role: string, capabilities: string[], status = "AVAILABLE"): Agent => ({
  id,
  name,
  role,
  capabilities,
  status,
  reliability_score: 0.9,
  version: "1.0.0",
  cost_profile: {},
});

/** Los 13 agentes reales del registro, uno por cada hueco de la especificación. */
const REGISTRY: Agent[] = [
  agent("a-product", "Product Validation Agent", "product", ["market_validation"]),
  agent("a-research", "Product Research Agent", "research", ["product_research"]),
  agent("a-supplier", "Supplier Sourcing Agent", "supplier", ["supplier_sourcing"]),
  agent("a-sourcing", "Supplier Sourcing Research Agent", "sourcing", ["supplier_sourcing_research"]),
  agent("a-finance", "Finance Validation Agent", "finance", ["financial_validation"]),
  agent("a-economics", "Economic Analysis and Risk Agent", "economics", ["economic_risk_analysis"]),
  agent("a-legal", "Legal Validation Agent", "legal", ["legal_validation"]),
  agent("a-compliance", "Legal Compliance Analysis Agent", "legal_compliance", ["legal_compliance_analysis"]),
  agent("a-cfo", "CFO Financial Health Agent", "cfo", ["cfo_financial_health_report"]),
  agent("a-operations", "Operations and Customer Service Agent", "operations", ["operations_fulfillment_management"]),
  agent("a-marketing", "Marketing Campaign Planning Agent", "marketing", ["marketing_campaign_planning"]),
  agent("a-ecommerce", "Ecommerce Storefront Generation Agent", "ecommerce", ["ecommerce_storefront_generation"]),
  agent("a-marketplace", "Marketplace Listing Optimization Agent", "marketplace", ["marketplace_listing_optimization"]),
];

const execution = (id: string, agentId: string, at: number, durationMs = 1000, success = true): AgentExecution => ({
  id,
  agent_id: agentId,
  capability: "run",
  duration_ms: durationMs,
  success,
  correlation_id: id,
  created_at: new Date(at).toISOString(),
});

const build = (over: Partial<Parameters<typeof buildGraph>[0]> = {}) => buildGraph({ agents: REGISTRY, executions: [], tasks: null, now: NOW, ...over });

// --- Layout -----------------------------------------------------------------------

test("el anillo de dominios deja libre la vertical del CEO y avanza en sentido horario", () => {
  assert.equal(domainAngle(0), -67.5);
  assert.equal(domainAngle(1), -22.5);
  assert.equal(domainAngle(7), 247.5);
  // Ninguno cae exactamente arriba (0°), que es donde está el CEO.
  for (let index = 0; index < 8; index++) assert.notEqual(((domainAngle(index) % 360) + 360) % 360, 0);
  // Los cuatro primeros dominios quedan al fondo y los cuatro últimos al frente,
  // repartidos a izquierda y derecha en el orden de la imagen de referencia.
  const x = (index: number) => ringPosition(domainAngle(index), LAYOUT.domainRadius, 0)[0];
  assert.ok(x(0) < 0 && x(1) < 0 && x(2) > 0 && x(3) > 0, "los cuatro del fondo mal repartidos");
  assert.ok(x(4) > 0 && x(5) > 0 && x(6) < 0 && x(7) < 0, "los cuatro del frente mal repartidos");
});

test("ringPosition redondea las coordenadas para no romper la hidratación", () => {
  const [x, y, z] = ringPosition(30, 2, 1);
  assert.equal(y, 1);
  assert.equal(x, Math.round(2 * Math.sin(30 * (Math.PI / 180)) * 10_000) / 10_000);
  const decimals = (value: number) => (String(value).split(".")[1] ?? "").length;
  assert.ok(decimals(x) <= 4, `x con ${decimals(x)} decimales`);
  assert.ok(decimals(z) <= 4, `z con ${decimals(z)} decimales`);
  assert.ok(ringPosition(37, 6.4, 0).every((value) => decimals(value) <= 4));
});

test("agentAngle centra al agente único y reparte a los dos de un dominio", () => {
  assert.equal(agentAngle(0, 0, 1), domainAngle(0));
  const [left, right] = [agentAngle(2, 0, 2), agentAngle(2, 1, 2)];
  assert.equal(left, domainAngle(2) - LAYOUT.agentSpreadDeg);
  assert.equal(right, domainAngle(2) + LAYOUT.agentSpreadDeg);
  assert.equal((left + right) / 2, domainAngle(2));
});

// --- Reparto de agentes -----------------------------------------------------------

test("agentSlots: los 13 agentes reales caen en los 8 dominios de la especificación", () => {
  const slots = agentSlots(REGISTRY);
  assert.equal(slots.length, 13);
  const byDomain = new Map<string, number>();
  for (const slot of slots) byDomain.set(slot.domain, (byDomain.get(slot.domain) ?? 0) + 1);
  assert.deepEqual(
    DOMAINS.map((domain) => byDomain.get(domain) ?? 0),
    // Investigación, Abastecimiento, Economía, Legal: 2 · Finanzas, Operaciones, Marketing: 1 · Comercio: 2
    [2, 2, 2, 2, 1, 1, 1, 2],
  );
  // Salen en el orden de los dominios, no en el del registro.
  assert.equal(slots[0].domain, "Investigación");
  assert.equal(slots[12].domain, "Comercio");
  assert.ok(slots.every((slot) => slot.agent !== undefined));
});

test("agentSlots: un registro vacío NO se rellena con ningún roster (M47)", () => {
  assert.deepEqual(agentSlots([]), []);
  const { nodes } = build({ agents: [] });
  assert.equal(nodes.filter((node) => node.type === "agent").length, 0);
  // Ni por el nombre: ninguno de los agentes del antiguo roster de demostración aparece.
  for (const label of ["Product Hunter", "Market Analyst", "Supplier Finder", "Acquisition Agent", "Storefront Builder"]) {
    assert.equal(nodes.some((node) => node.label === label), false, label);
  }
});

// --- Grafo ------------------------------------------------------------------------

test("buildGraph: CEO, núcleo, 8 dominios y 13 agentes, con la jerarquía completa", () => {
  const { nodes, edges } = build();
  assert.equal(nodes.filter((node) => node.type === "ceo").length, 1);
  assert.equal(nodes.filter((node) => node.type === "core").length, 1);
  assert.equal(nodes.filter((node) => node.type === "domain").length, 8);
  assert.equal(nodes.filter((node) => node.type === "agent").length, 13);

  // El CEO está por encima del núcleo y el núcleo en el centro exacto.
  assert.deepEqual(nodes.find((node) => node.id === CORE_ID)?.position, [0, 0, 0]);
  assert.equal(nodes.find((node) => node.id === CEO_ID)?.position[1], LAYOUT.ceoHeight);

  // Jerarquía: CEO→núcleo, núcleo→8 dominios, dominio→13 agentes.
  const hierarchy = edges.filter((edge) => edge.type === "hierarchy");
  assert.equal(hierarchy.length, 1 + 8 + 13);
  assert.ok(hierarchy.some((edge) => edge.source === CEO_ID && edge.target === CORE_ID));
});

test("buildGraph: cada agente se coloca en el anillo exterior, cerca de su dominio", () => {
  const { nodes } = build();
  const radius = (node: GraphNode) => Math.round(Math.hypot(node.position[0], node.position[2]) * 100) / 100;
  for (const node of nodes.filter((n) => n.type === "agent")) assert.equal(radius(node), LAYOUT.agentRadius);
  for (const node of nodes.filter((n) => n.type === "domain")) assert.equal(radius(node), LAYOUT.domainRadius);
  // El layout es determinista: dos construcciones dan las mismas posiciones.
  const again = build({ now: NOW + 5_000 });
  assert.deepEqual(nodes.map((n) => n.position), again.nodes.map((n) => n.position));
});

// --- Estado de los nodos: solo del registro ---------------------------------------------------------------------------------

test("buildGraph: el estado de un agente sale SOLO del registro; ni las tareas ni ninguna decisión lo cambian", () => {
  const tasks = [
    task("t1", "RUNNING", "market_validation"),
    task("t2", "FAILED", "financial_validation", { error: "boom" }),
    task("t3", "WAITING_APPROVAL", "legal_validation"),
    task("t4", "COMPLETED", "supplier_sourcing"),
  ];
  const sin = build({ tasks: null });
  const con = build({ tasks });
  assert.deepEqual(con.nodes.map((n) => [n.id, n.status]), sin.nodes.map((n) => [n.id, n.status]));
  for (const node of con.nodes) assert.ok(["available"].includes(node.status), `${node.id}: ${node.status}`);
});

test("buildGraph: una tarea FAILED NO marca a ningún agente como FAILED ni BLOQUEADO (la tarea no trae agente asignado)", () => {
  const { nodes, edges } = build({ tasks: [task("t", "FAILED", "financial_validation", { error: "boom" })] });
  assert.equal(nodes.find((n) => n.id === "a-finance")?.status, "available");
  assert.equal(nodes.find((n) => n.type === "domain" && n.domain === "Finanzas")?.status, "available");
  assert.equal(edges.filter((e) => e.type === "incident").length, 0);
  assert.equal(nodes.find((n) => n.id === CORE_ID)?.status, "available");
});

const withRelation = (item: Task, relation: AgentRelation): Task => ({ ...item, agent_relation: relation });
const relationOf = (status: AgentRelation["status"], over: Partial<AgentRelation> = {}): AgentRelation => ({
  status,
  assigned_agent_id: null,
  assigned_agent_known: null,
  executed_by_agent_id: null,
  reassigned: false,
  executions: [],
  ...over,
});
const ranBy = (agentId: string, assignedTo: string | null): AgentRelation["executions"][number] => ({
  source: "execution_log",
  execution_id: `e-${agentId}`,
  agent_id: agentId,
  agent_known: true,
  success: true,
  attempt: 1,
  assigned_agent_id: assignedTo,
  started_at: null,
  completed_at: null,
  created_at: "2026-10-20T10:00:00Z",
});

test("buildGraph: un agente lleva las tareas que el backend le ASIGNÓ o que EJECUTÓ; compartir capacidad no basta", () => {
  const assigned = withRelation(
    task("t", "PENDING", "financial_validation"),
    relationOf("ASSIGNED", { assigned_agent_id: "a-finance", assigned_agent_known: true }),
  );
  const sameCapabilityNoRelation = task("u", "COMPLETED", "financial_validation");
  const { nodes } = build({ tasks: [assigned, sameCapabilityNoRelation] });

  assert.deepEqual(nodes.find((n) => n.id === "a-finance")?.agentTasks?.map((t) => [t.id, t.assigned, t.executed]), [["t", true, false]]);
  assert.equal(nodes.find((n) => n.id === "a-product")?.agentTasks, undefined);
  assert.equal(nodes.find((n) => n.id === "a-marketing")?.agentTasks, undefined);
});

test("buildGraph: una desviación aparece en el agente que ejecutó y en el asignado, y la tarea FAILED no marca al agente", () => {
  const deviated = withRelation(
    task("t", "FAILED", "financial_validation", { error: "boom" }),
    relationOf("MISMATCH", {
      assigned_agent_id: "a-finance",
      assigned_agent_known: true,
      executed_by_agent_id: "a-product",
      executions: [ranBy("a-product", "a-finance")],
    }),
  );
  const { nodes } = build({ tasks: [deviated] });
  const finance = nodes.find((n) => n.id === "a-finance")!;
  const product = nodes.find((n) => n.id === "a-product")!;

  assert.deepEqual([finance.agentTasks?.[0].deviation, finance.agentTasks?.[0].assigned, finance.agentTasks?.[0].executed], [true, true, false]);
  assert.deepEqual([product.agentTasks?.[0].deviation, product.agentTasks?.[0].assigned, product.agentTasks?.[0].executed], [true, false, true]);
  assert.equal(finance.agentTasks?.[0].state, "Desviación");
  assert.equal(finance.agentTasks?.[0].error, "boom");
  assert.equal(finance.status, "available");
});

test("buildGraph: sin tareas leídas, ningún agente lleva tareas (ni una lista vacía que parezca un hecho) y el núcleo no lleva las de la misión", () => {
  for (const tasks of [null, []]) {
    const { nodes } = build({ tasks });
    for (const node of nodes.filter((n) => n.type === "agent")) assert.equal(node.agentTasks, undefined, String(tasks));
    assert.equal(nodes.find((n) => n.id === CORE_ID)?.missionTasks, undefined, String(tasks));
  }
});

test("buildGraph: sin la relación del backend (un backend anterior) ningún agente recibe la tarea: ni por capacidad ni «sin asignar»", () => {
  const { nodes } = build({ tasks: [task("t", "COMPLETED", "financial_validation")] });
  for (const node of nodes.filter((n) => n.type === "agent")) assert.equal(node.agentTasks, undefined, node.id);
  assert.equal(nodes.find((n) => n.id === CORE_ID)?.missionTasks?.[0].status, "UNAVAILABLE");
});

test("buildGraph: ningún nodo lleva campos de demostración (tarea, progreso, proyecto, coste, evaluación, isDemo)", () => {
  const { nodes } = build({ executions: [execution("e1", "a-product", NOW - 1000)], tasks: [task("t", "COMPLETED", "market_validation")] });
  for (const node of nodes) {
    for (const key of ["task", "progress", "projectName", "isDemo"]) assert.equal(key in node, false, `${node.id}.${key}`);
    for (const key of ["costToday", "evaluationScore", "handoffs", "humanGates", "activeEvents"]) assert.equal(node.metrics !== undefined && key in node.metrics, false, `${node.id}.metrics.${key}`);
  }
});

test("buildGraph: las métricas de cada agente salen de sus ejecuciones reales (y el coste no existe)", () => {
  const { nodes } = build({
    executions: [
      execution("e1", "a-product", NOW - 3_600_000, 1_000),
      execution("e2", "a-product", NOW - 7_200_000, 3_000, false),
      execution("e3", "a-legal", NOW - 40 * 86_400_000, 500),
    ],
  });
  const product = nodes.find((node) => node.id === "a-product")!;
  assert.equal(product.metrics?.runs, 2);
  assert.equal(product.metrics?.successRate, 0.5);
  assert.equal(product.metrics?.latencyMs, 2_000);
  assert.equal(product.lastActivityAt, NOW - 3_600_000);
  // Sin ejecuciones, no se inventa ni tasa de éxito ni latencia.
  const marketing = nodes.find((node) => node.id === "a-marketing")!;
  assert.equal(marketing.metrics?.runs, 0);
  assert.equal(marketing.metrics?.successRate, undefined);
  assert.equal(marketing.metrics?.latencyMs, undefined);
});

test("worstStatus", () => {
  assert.equal(worstStatus([]), "inactive");
  assert.equal(worstStatus(["available", "running"]), "running");
  assert.equal(worstStatus(["running", "blocked", "waiting"]), "blocked");
  assert.equal(worstStatus(["blocked", "error"]), "error");
});

test("buildGraph: el CEO y el núcleo no se «encienden» con nada que no sea una medición: su estado es «Disponible»", () => {
  const { nodes } = build({ tasks: [task("t", "RUNNING", "market_validation")] });
  assert.equal(nodes.find((n) => n.id === CEO_ID)?.status, "available");
  assert.equal(nodes.find((n) => n.id === CORE_ID)?.status, "available");
});

// --- Dependencias: solo de `depends_on` ----------------------------------------------------------------------------------------

test("buildGraph: sin tareas NO hay ninguna arista de dependencia (se retiraron los handoffs de demostración)", () => {
  for (const tasks of [null, [], [task("a", "COMPLETED", "market_validation"), task("b", "COMPLETED", "supplier_sourcing")]]) {
    assert.equal(build({ tasks }).edges.filter((e) => e.type === "dependency").length, 0, JSON.stringify(tasks?.length ?? tasks));
  }
});

test("buildGraph: con `depends_on` real se dibuja la dependencia entre los dominios de las capacidades, y nada más", () => {
  const tasks = [
    task("p", "COMPLETED", "market_validation"),
    task("s", "COMPLETED", "supplier_sourcing", { depends_on: ["p"] }),
    task("f", "COMPLETED", "financial_validation", { depends_on: ["p", "s"] }),
    task("d", "COMPLETED", "decision_synthesis", { depends_on: ["p", "s", "f"] }),
  ];
  const { nodes, edges } = build({ tasks });
  const idOf = (domain: string) => nodes.find((n) => n.type === "domain" && n.domain === domain)!.id;
  const dependency = edges.filter((e) => e.type === "dependency");
  assert.deepEqual(
    dependency.map((e) => [e.source, e.target]),
    [
      [idOf("Investigación"), idOf("Abastecimiento")],
      [idOf("Investigación"), idOf("Economía")],
      [idOf("Abastecimiento"), idOf("Economía")],
    ],
  );
  assert.ok(dependency.every((e) => e.active === false && e.status === "normal"));
});

// --- Modos ------------------------------------------------------------------------

const BUSY_AND_BLOCKED = REGISTRY.map((entry) => (entry.id === "a-product" ? { ...entry, status: "BUSY" } : entry.id === "a-finance" ? { ...entry, status: "BLOCKED" } : entry.id === "a-legal" ? { ...entry, status: "WAITING" } : entry));

test("modo Arquitectura: solo jerarquía y sin nada atenuado", () => {
  const { nodes, edges } = build({ agents: BUSY_AND_BLOCKED, tasks: [task("p", "COMPLETED", "market_validation"), task("s", "COMPLETED", "supplier_sourcing", { depends_on: ["p"] })] });
  const view = applyMode(nodes, edges, "architecture");
  assert.ok(view.edges.every((edge) => edge.type === "hierarchy"));
  assert.equal(view.dimmed.size, 0);
});

test("modo Ejecución: con un agente que el REGISTRO da por ocupado, atenúa a los parados y no enseña incidencias", () => {
  const { nodes, edges } = build({ agents: BUSY_AND_BLOCKED });
  const view = applyMode(nodes, edges, "execution");
  assert.equal(view.dimmed.has("a-product"), false);
  assert.equal(view.dimmed.has("a-marketing"), true);
  assert.ok(view.edges.every((edge) => edge.type !== "incident"));
  assert.ok(view.edges.some((edge) => edge.type === "flow" && edge.source === "a-product"));
});

test("modo Ejecución: con un registro sin ningún agente ocupado, ningún agente queda sin atenuar ni hay flujos", () => {
  const { nodes, edges } = build();
  const view = applyMode(nodes, edges, "execution");
  assert.ok(nodes.filter((n) => n.type === "agent").every((n) => view.dimmed.has(n.id)));
  assert.equal(view.edges.filter((e) => e.type === "flow").length, 0);
});

test("modo Incidencias: solo quedan sin atenuar los bloqueados, en error o esperando SEGÚN EL REGISTRO", () => {
  const { nodes, edges } = build({ agents: BUSY_AND_BLOCKED });
  const view = applyMode(nodes, edges, "incidents");
  assert.equal(view.dimmed.has("a-finance"), false);
  assert.equal(view.dimmed.has("a-legal"), false, "esperando también es algo que mirar");
  assert.equal(view.dimmed.has("a-marketing"), true);
  assert.ok(view.edges.some((edge) => edge.type === "incident"));
});

// --- Foco -------------------------------------------------------------------------

test("relatedIds devuelve el nodo y sus conexiones directas", () => {
  const { edges } = build();
  assert.equal(relatedIds(edges, null).size, 0);
  const related = relatedIds(edges, CORE_ID);
  assert.ok(related.has(CORE_ID));
  assert.ok(related.has(CEO_ID));
  // Los 8 dominios cuelgan del núcleo; los agentes no son vecinos directos suyos.
  assert.equal(related.size, 1 + 1 + 8);
  assert.equal(related.has("a-product"), false);
});

test("meanLatencyMs: sin log leído o vacío no hay latencia (ni un número de relleno)", () => {
  assert.equal(meanLatencyMs(null), null);
  assert.equal(meanLatencyMs([]), null);
  assert.equal(meanLatencyMs([execution("e1", "a-product", NOW, 400), execution("e2", "a-product", NOW, 600)]), 500);
});

// --- Decision Engine --------------------------------------------------------------

test("buildGraph: cada conexión con el núcleo entra por su propia zona del cerebro", () => {
  const { nodes, edges } = build();
  const domains = nodes.filter((node) => node.type === "domain");

  const ceo = edges.find((edge) => edge.id === "ceo-core");
  assert.deepEqual(ceo?.anchor, CEO_ANCHOR);

  const anchors = domains.map((domain) => edges.find((edge) => edge.id === `core-${domain.id}`)?.anchor);
  assert.ok(anchors.every(Boolean), "hay dominios sin zona neural");
  assert.equal(new Set(anchors.map((anchor) => anchor!.join(","))).size, domains.length, "dos dominios entran por el mismo punto");
  domains.forEach((domain, index) => {
    assert.deepEqual(anchors[index], zoneAnchor(domainAngle(index)));
  });
});

test("buildGraph: el flujo y las incidencias de un agente entran por la zona de su dominio", () => {
  const { nodes, edges } = build({ agents: BUSY_AND_BLOCKED });
  const contextual = edges.filter((edge) => edge.type === "flow" || edge.type === "incident");
  assert.ok(contextual.length > 0, "sin conexiones contextuales que comprobar");
  for (const edge of contextual) {
    const agentNode = nodes.find((node) => node.id === edge.source)!;
    const index = DOMAINS.indexOf(agentNode.domain!);
    assert.deepEqual(edge.anchor, zoneAnchor(domainAngle(index)), `${agentNode.label} entra por la zona equivocada`);
  }
});

test("buildGraph: el núcleo solo publica lo que tiene fuente: la latencia media del log y nada más", () => {
  const empty = build();
  const core = empty.nodes.find((node) => node.id === CORE_ID)!;
  assert.deepEqual(core.metrics ?? {}, {});
  const withLog = build({ executions: [execution("e1", "a-product", NOW, 800), execution("e2", "a-legal", NOW, 1_200)] }).nodes.find((node) => node.id === CORE_ID)!;
  assert.deepEqual(withLog.metrics, { latencyMs: 1_000 });
});

test("neuralZones: ocho zonas en el orden de los dominios, con el estado de cada uno", () => {
  const { nodes } = build();
  const zones = neuralZones(nodes);
  assert.equal(zones.length, DOMAINS.length);
  zones.forEach((zone, index) => {
    const domain = nodes.find((node) => node.type === "domain" && node.domain === DOMAINS[index])!;
    assert.equal(zone.label, DOMAINS[index]);
    assert.equal(zone.id, domain.id);
    assert.equal(zone.status, domain.status);
    assert.equal(zone.angle, domainAngle(index));
  });
});

// --- M47 · Commit 1: estados reales del registro y lecturas que fallan -------------------------------------------------

const withStatus = (status: string): Agent[] => REGISTRY.map((entry, index) => (index === 0 ? { ...entry, status } : entry));

test("nodeStatusOfRegistry: los siete estados del backend y ninguno más", () => {
  const status = (raw: string) => nodeStatusOfRegistry(readAgentStatus(raw));
  assert.equal(status("AVAILABLE"), "available");
  assert.equal(status("BUSY"), "running");
  assert.equal(status("WAITING"), "waiting");
  assert.equal(status("BLOCKED"), "blocked");
  assert.equal(status("DEGRADED"), "degraded");
  assert.equal(status("DISABLED"), "inactive");
  assert.equal(status("FAILED"), "error");
  // El backend no envía OFFLINE ni ERROR: llegan como lo que son, un texto desconocido; jamás como «disponible».
  for (const raw of ["OFFLINE", "ERROR", "ONLINE", "available", "", "x"]) assert.equal(status(raw), "unknown", raw);
});

test("buildGraph: BLOCKED, DEGRADED, DISABLED y FAILED NO se dibujan como «Disponible»", () => {
  const expected: Record<string, string> = { BLOCKED: "blocked", DEGRADED: "degraded", DISABLED: "inactive", FAILED: "error", OFFLINE: "unknown" };
  for (const [raw, status] of Object.entries(expected)) {
    const node = build({ agents: withStatus(raw) }).nodes.find((n) => n.id === "a-product")!;
    assert.equal(node.status, status, raw);
    assert.notEqual(node.status, "available");
    assert.equal(node.registry && node.registry.kind === "known" ? node.registry.status : node.registry?.raw, raw);
  }
});

test("buildGraph: ni las tareas ni la decisión «suavizan» ni «endurecen» lo que dice el registro", () => {
  const tasks = [task("t", "COMPLETED", "market_validation")];
  for (const [raw, status] of [["DEGRADED", "degraded"], ["FAILED", "error"], ["BLOCKED", "blocked"], ["DISABLED", "inactive"], ["OFFLINE", "unknown"], ["AVAILABLE", "available"]] as const) {
    const node = build({ agents: withStatus(raw), tasks }).nodes.find((n) => n.id === "a-product")!;
    assert.equal(node.status, status, raw);
  }
});

test("un agente degradado o desconocido contamina su dominio y abre una incidencia; DEGRADED no es «esperando»", () => {
  for (const raw of ["DEGRADED", "OFFLINE"]) {
    const { nodes, edges } = build({ agents: withStatus(raw) });
    const agentNode = nodes.find((node) => node.id === "a-product")!;
    const domain = nodes.find((node) => node.type === "domain" && node.domain === agentNode.domain)!;
    assert.ok(["degraded", "unknown"].includes(domain.status), `${raw}: el dominio sigue sano (${domain.status})`);
    assert.equal(edges.filter((edge) => edge.type === "incident").length, 1, raw);
  }
  assert.notEqual(nodeStatusOfRegistry(readAgentStatus("DEGRADED")), nodeStatusOfRegistry(readAgentStatus("WAITING")));
  assert.equal(worstStatus(["available", "degraded", "waiting"]), "degraded");
  assert.equal(worstStatus(["running", "unknown"]), "unknown");
  assert.equal(worstStatus(["degraded", "blocked"]), "blocked");
});

test("buildGraph: sin el log de ejecuciones leído no hay métricas de ejecución, ni un 0 (y el coste no existe en ningún caso)", () => {
  const { nodes } = build({ executions: null });
  for (const node of nodes.filter((n) => n.type === "agent")) {
    assert.equal(node.metrics?.runs, undefined, node.label);
    assert.equal(node.metrics?.successRate, undefined, node.label);
    assert.equal(node.metrics?.latencyMs, undefined, node.label);
    assert.equal(node.metrics !== undefined && "costToday" in node.metrics, false, node.label);
  }
  // Con el log leído y vacío, el cero SÍ es un hecho.
  const read = build().nodes.find((n) => n.id === "a-product")!;
  assert.equal(read.metrics?.runs, 0);
});
