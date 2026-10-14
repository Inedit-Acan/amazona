import assert from "node:assert/strict";
import { test } from "node:test";
import type { Agent, AgentExecution, Decision } from "./api.ts";
import { readAgentStatus } from "./agent-status.ts";
import { CANONICAL_AGENTS, DEMO_CORE_METRICS, DEMO_PROJECT, DOMAINS } from "./demo/neural-nexus.ts";
import { CEO_ANCHOR, zoneAnchor } from "./decision-engine.ts";
import {
  CEO_ID,
  CORE_ID,
  LAYOUT,
  agentAngle,
  agentSlots,
  applyMode,
  buildGraph,
  coreStatus,
  domainAngle,
  hudMetrics,
  meanLatencyMs,
  neuralZones,
  nodeStatusOfRegistry,
  relatedIds,
  ringPosition,
  worstStatus,
  type GraphNode,
} from "./neural-nexus.ts";

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

const decision = (over: Partial<Decision> = {}): Decision => ({
  id: "d1",
  project_id: "AMZ-REAL-1",
  status: "GO",
  opportunity_score: 0.8,
  confidence: 0.75,
  rationale: null,
  correlation_id: "corr-1",
  evidence: [],
  ...over,
});

const execution = (id: string, agentId: string, at: number, durationMs = 1000, success = true): AgentExecution => ({
  id,
  agent_id: agentId,
  capability: "run",
  duration_ms: durationMs,
  success,
  correlation_id: id,
  created_at: new Date(at).toISOString(),
});

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

test("agentSlots: un registro vacío NO se rellena con el roster canónico de demostración (M47)", () => {
  assert.deepEqual(agentSlots([]), []);
  const { nodes } = buildGraph({ agents: [], executions: [], decision: null, now: NOW });
  assert.equal(nodes.filter((node) => node.type === "agent").length, 0);
  assert.equal(nodes.some((node) => node.isDemo), false, "ningún nodo del grafo puede ser de demostración");
  // Ni siquiera por el nombre: ningún agente del roster canónico aparece.
  const labels = new Set(CANONICAL_AGENTS.map((entry) => entry.label));
  assert.equal(nodes.some((node) => labels.has(node.label)), false);
});

// --- Grafo ------------------------------------------------------------------------

test("buildGraph: CEO, núcleo, 8 dominios y 13 agentes, con la jerarquía completa", () => {
  const { nodes, edges } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
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
  const { nodes } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
  const radius = (node: GraphNode) => Math.round(Math.hypot(node.position[0], node.position[2]) * 100) / 100;
  for (const node of nodes.filter((n) => n.type === "agent")) assert.equal(radius(node), LAYOUT.agentRadius);
  for (const node of nodes.filter((n) => n.type === "domain")) assert.equal(radius(node), LAYOUT.domainRadius);
  // El layout es determinista: dos construcciones dan las mismas posiciones.
  const again = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW + 5_000 });
  assert.deepEqual(nodes.map((n) => n.position), again.nodes.map((n) => n.position));
});

test("buildGraph: la decisión del CEO pone a ejecutar a los agentes con evidencia y espera a los demás", () => {
  const { nodes } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] }),
    now: NOW,
  });
  const statusOf = (id: string) => nodes.find((node) => node.id === id)?.status;
  assert.equal(statusOf("a-product"), "running");
  // Los otros tres validadores de la decisión quedan esperando su evidencia.
  assert.equal(statusOf("a-supplier"), "waiting");
  assert.equal(statusOf("a-finance"), "waiting");
  assert.equal(statusOf("a-legal"), "waiting");
  // Los agentes que no participan en esta decisión conservan su estado del registro.
  assert.equal(statusOf("a-marketing"), "available");
  assert.equal(statusOf(CEO_ID), "running");
});

test("buildGraph: el veto financiero y el NO_GO legal bloquean a su agente", () => {
  const { nodes, edges } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({
      status: "NO_GO",
      evidence: [
        { source: "finance_validation", summary: "veto", data: { finance_veto: true } },
        { source: "legal_validation", summary: "no", data: { legal_status: "NO_GO" } },
      ],
    }),
    now: NOW,
  });
  assert.equal(nodes.find((node) => node.id === "a-finance")?.status, "blocked");
  assert.equal(nodes.find((node) => node.id === "a-legal")?.status, "blocked");
  // El dominio hereda lo peor de sus agentes y se abre una arista de incidencia.
  assert.equal(nodes.find((node) => node.type === "domain" && node.domain === "Legal")?.status, "blocked");
  assert.equal(edges.filter((edge) => edge.type === "incident").length, 2);
  assert.equal(nodes.find((node) => node.id === CORE_ID)?.status, "error");
});

test("buildGraph: las métricas de cada agente salen de sus ejecuciones reales", () => {
  const { nodes } = buildGraph({
    agents: REGISTRY,
    executions: [
      execution("e1", "a-product", NOW - 3_600_000, 1_000),
      execution("e2", "a-product", NOW - 7_200_000, 3_000, false),
      execution("e3", "a-legal", NOW - 40 * 86_400_000, 500),
    ],
    decision: null,
    now: NOW,
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

test("worstStatus y coreStatus", () => {
  assert.equal(worstStatus([]), "inactive");
  assert.equal(worstStatus(["available", "running"]), "running");
  assert.equal(worstStatus(["running", "blocked", "waiting"]), "blocked");
  assert.equal(worstStatus(["blocked", "error"]), "error");
  assert.equal(coreStatus(null), "available");
  assert.equal(coreStatus(decision({ status: "GO" })), "running");
  assert.equal(coreStatus(decision({ status: "NO_GO" })), "error");
  assert.equal(coreStatus(decision({ status: "REVIEW" })), "waiting");
});

// --- Modos ------------------------------------------------------------------------

test("modo Arquitectura: solo jerarquía y sin nada atenuado", () => {
  const { nodes, edges } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] }),
    now: NOW,
  });
  const view = applyMode(nodes, edges, "architecture");
  assert.ok(view.edges.every((edge) => edge.type === "hierarchy"));
  assert.equal(view.dimmed.size, 0);
});

test("modo Ejecución: atenúa los agentes parados y no enseña incidencias", () => {
  const { nodes, edges } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] }),
    now: NOW,
  });
  const view = applyMode(nodes, edges, "execution");
  assert.equal(view.dimmed.has("a-product"), false);
  assert.equal(view.dimmed.has("a-marketing"), true);
  assert.ok(view.edges.every((edge) => edge.type !== "incident"));
  assert.ok(view.edges.some((edge) => edge.type === "flow" && edge.source === "a-product"));
});

test("modo Incidencias: solo quedan sin atenuar los bloqueados, en error o esperando", () => {
  const { nodes, edges } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({
      status: "NO_GO",
      evidence: [{ source: "finance_validation", summary: "veto", data: { finance_veto: true } }],
    }),
    now: NOW,
  });
  const view = applyMode(nodes, edges, "incidents");
  assert.equal(view.dimmed.has("a-finance"), false);
  // Los otros validadores están «esperando», que también es algo que mirar.
  assert.equal(view.dimmed.has("a-legal"), false);
  assert.equal(view.dimmed.has("a-marketing"), true);
  assert.ok(view.edges.some((edge) => edge.type === "incident"));
});

// --- Foco -------------------------------------------------------------------------

test("relatedIds devuelve el nodo y sus conexiones directas", () => {
  const { edges } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
  assert.equal(relatedIds(edges, null).size, 0);
  const related = relatedIds(edges, CORE_ID);
  assert.ok(related.has(CORE_ID));
  assert.ok(related.has(CEO_ID));
  // Los 8 dominios cuelgan del núcleo; los agentes no son vecinos directos suyos.
  assert.equal(related.size, 1 + 1 + 8);
  assert.equal(related.has("a-product"), false);
});

// --- HUD --------------------------------------------------------------------------

test("hudMetrics: sin decisión no hay proyecto, ni progreso, ni eventos: ni el 68 % ni AMZ-2026-003 ni los 3 eventos (M47)", () => {
  const { nodes } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
  const hud = hudMetrics(nodes, [execution("e1", "a-product", NOW, 800), execution("e2", "a-legal", NOW, 1_200)], null);
  assert.equal(hud.totalAgents, 13);
  assert.equal(hud.activeAgents, 0);
  assert.equal(hud.latencyMs, 1_000);
  assert.equal(hud.projectName, null);
  assert.equal(hud.progress, null);
  assert.equal(hud.activeEvents, null);
  const dump = JSON.stringify(hud);
  for (const forbidden of [DEMO_PROJECT.code, String(DEMO_PROJECT.progress), String(DEMO_CORE_METRICS.latencyMs)]) {
    assert.equal(dump.includes(forbidden), false, `el HUD contiene el valor de demostración ${forbidden}`);
  }
});

test("hudMetrics: si el log de ejecuciones no se pudo leer, la latencia es «sin dato» y no un número", () => {
  const { nodes } = buildGraph({ agents: REGISTRY, executions: null, decision: null, now: NOW });
  const hud = hudMetrics(nodes, null, null);
  assert.equal(hud.latencyMs, null);
  assert.equal(meanLatencyMs(null), null);
  assert.equal(meanLatencyMs([]), null);
  assert.equal(meanLatencyMs([execution("e1", "a-product", NOW, 400), execution("e2", "a-product", NOW, 600)]), 500);
});

test("hudMetrics: con decisión, el proyecto, el progreso y los eventos son reales", () => {
  const withDecision = decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] });
  const { nodes } = buildGraph({ agents: REGISTRY, executions: [], decision: withDecision, now: NOW });
  const hud = hudMetrics(nodes, [], withDecision);
  assert.equal(hud.projectName, "AMZ-REAL-1");
  assert.equal(hud.progress, 0.75);
  assert.equal(hud.activeEvents, 1);
  assert.equal(hud.activeAgents, 1);
  assert.equal(hud.latencyMs, null);
});

// --- Decision Engine --------------------------------------------------------------

test("buildGraph: cada conexión con el núcleo entra por su propia zona del cerebro", () => {
  const { nodes, edges } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
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
  const { nodes, edges } = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({
      evidence: [
        { source: "product_validation", summary: "ok", data: {} },
        { source: "legal_validation", summary: "no", data: { legal_status: "NO_GO" } },
      ],
    }),
    now: NOW,
  });
  const contextual = edges.filter((edge) => edge.type === "flow" || edge.type === "incident");
  assert.ok(contextual.length > 0, "sin conexiones contextuales que comprobar");
  for (const edge of contextual) {
    const agent = nodes.find((node) => node.id === edge.source)!;
    const index = DOMAINS.indexOf(agent.domain!);
    assert.deepEqual(edge.anchor, zoneAnchor(domainAngle(index)), `${agent.label} entra por la zona equivocada`);
  }
});

test("buildGraph: el núcleo solo publica lo que tiene fuente: sin decisión no hay eventos, handoffs ni puertas humanas", () => {
  const empty = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
  const core = empty.nodes.find((node) => node.id === CORE_ID)!;
  assert.equal(core.metrics?.activeEvents, undefined);
  assert.equal(core.metrics?.handoffs, undefined);
  assert.equal(core.metrics?.humanGates, undefined);
  assert.equal(core.metrics?.latencyMs, undefined);
  assert.equal(core.projectName, undefined);
  assert.equal(core.progress, undefined);
  assert.equal(core.isDemo, false);

  const real = buildGraph({
    agents: REGISTRY,
    executions: [],
    decision: decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] }),
    now: NOW,
  });
  const withDecision = real.nodes.find((node) => node.id === CORE_ID)!;
  assert.equal(withDecision.metrics?.activeEvents, 1);
  assert.equal(withDecision.isDemo, false);
});

test("neuralZones: ocho zonas en el orden de los dominios, con el estado de cada uno", () => {
  const { nodes } = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW });
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
    const node = buildGraph({ agents: withStatus(raw), executions: [], decision: null, now: NOW }).nodes.find((n) => n.id === "a-product")!;
    assert.equal(node.status, status, raw);
    assert.notEqual(node.status, "available");
    assert.equal(node.registry && node.registry.kind === "known" ? node.registry.status : node.registry?.raw, raw);
  }
});

test("buildGraph: la decisión del CEO no convierte en «ejecutando» a un agente que el registro da por degradado o fallido", () => {
  const withEvidence = decision({ evidence: [{ source: "product_validation", summary: "ok", data: {} }] });
  for (const [raw, status] of [["DEGRADED", "degraded"], ["FAILED", "error"], ["BLOCKED", "blocked"], ["DISABLED", "inactive"], ["OFFLINE", "unknown"]] as const) {
    const node = buildGraph({ agents: withStatus(raw), executions: [], decision: withEvidence, now: NOW }).nodes.find((n) => n.id === "a-product")!;
    assert.equal(node.status, status, raw);
  }
  // Con un registro sano, la misma evidencia sí lo pone a ejecutar.
  assert.equal(buildGraph({ agents: REGISTRY, executions: [], decision: withEvidence, now: NOW }).nodes.find((n) => n.id === "a-product")?.status, "running");
});

test("un agente degradado o desconocido contamina su dominio y abre una incidencia; DEGRADED no es «esperando»", () => {
  for (const raw of ["DEGRADED", "OFFLINE"]) {
    const { nodes, edges } = buildGraph({ agents: withStatus(raw), executions: [], decision: null, now: NOW });
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

test("buildGraph: sin el log de ejecuciones leído no hay métricas de ejecución, ni un 0 ni un 0 €", () => {
  const { nodes } = buildGraph({ agents: REGISTRY, executions: null, decision: null, now: NOW });
  for (const node of nodes.filter((n) => n.type === "agent")) {
    assert.equal(node.metrics?.runs, undefined, node.label);
    assert.equal(node.metrics?.successRate, undefined, node.label);
    assert.equal(node.metrics?.latencyMs, undefined, node.label);
    assert.equal(node.metrics?.costToday, undefined, node.label);
  }
  // Con el log leído y vacío, el cero SÍ es un hecho.
  const read = buildGraph({ agents: REGISTRY, executions: [], decision: null, now: NOW }).nodes.find((n) => n.id === "a-product")!;
  assert.equal(read.metrics?.runs, 0);
});
