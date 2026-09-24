import type { Agent, AgentExecution, Decision } from "./api.ts";
import { teamOf } from "./agents.ts";
import { parseUtc } from "./dates.ts";
import { COST_PER_RUN } from "./demo/agents.ts";
import {
  CANONICAL_AGENTS,
  DEMO_CORE_METRICS,
  DEMO_HANDOFFS,
  DEMO_PROJECT,
  DEMO_TASKS,
  DOMAINS,
  DOMAIN_DESCRIPTION,
  demoEvaluation,
  demoProgress,
  demoTaskIndex,
  type DomainKey,
} from "./demo/neural-nexus.ts";

// Modelo del grafo de agentes del Director ejecutivo («Neural Nexus»,
// docs/design/KOVA_Neural_Nexus_especificacion_Claude_Code.md). Cuatro niveles:
// CEO → Decision Engine → 8 dominios → 13 agentes. El layout es DETERMINISTA y
// estable entre sesiones: las posiciones se calculan aquí, no las decide un
// force-graph. Real: los agentes del registro con su estado, el log de
// ejecuciones y la decisión del CEO con sus evidencias. Demo
// (lib/demo/neural-nexus.ts): la tarea en curso, el progreso, los handoffs
// entre dominios y las métricas del Decision Engine.

export type NodeType = "ceo" | "core" | "domain" | "agent";
export type NodeStatus = "available" | "running" | "waiting" | "blocked" | "error" | "inactive";
export type GraphMode = "architecture" | "execution" | "incidents";
export type EdgeType = "hierarchy" | "flow" | "dependency" | "incident";

export const CORE_ID = "core";
export const CEO_ID = "ceo";

export const STATUS_LABEL: Record<NodeStatus, string> = {
  available: "Disponible",
  running: "Ejecutando",
  waiting: "Esperando",
  blocked: "Bloqueado",
  error: "Error",
  inactive: "Inactivo",
};

export const MODE_LABEL: Record<GraphMode, string> = {
  architecture: "Arquitectura",
  execution: "Ejecución",
  incidents: "Incidencias",
};

export interface NodeMetrics {
  successRate?: number;
  latencyMs?: number;
  costToday?: number;
  evaluationScore?: number;
  runs?: number;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  domain?: DomainKey;
  /** Posición determinista [x, y, z]; el mismo dato lo usa la vista 2D. */
  position: [number, number, number];
  status: NodeStatus;
  description: string;
  projectName?: string;
  task?: string;
  progress?: number;
  lastActivityAt?: number;
  metrics?: NodeMetrics;
  /** El estado o la tarea del nodo son de demostración. */
  isDemo: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  active: boolean;
  status: "normal" | "warning" | "error";
}

// --- Layout determinista --------------------------------------------------------------

/** Radios de cada anillo y altura de cada nivel. */
export const LAYOUT = {
  ceoHeight: 4.2,
  coreHeight: 0,
  domainRadius: 3.5,
  domainHeight: 0.15,
  agentRadius: 6.4,
  agentHeight: -0.55,
  /** Media separación entre dominios: el anillo arranca girado para dejar
   * libre la vertical del CEO. */
  startAngleDeg: -22.5,
  stepDeg: 45,
  /** Separación de los agentes de un dominio a cada lado de su ángulo. */
  agentSpreadDeg: 12,
};

const RAD = Math.PI / 180;
/** Las coordenadas se redondean: un seno con distinto último decimal entre el
 * servidor y el navegador rompería la hidratación de la vista 2D. */
const round4 = (value: number) => Math.round(value * 10_000) / 10_000;

/** Punto del anillo en el ángulo `deg`, medido en sentido horario desde arriba
 * (con la cámara por defecto, 0° queda al fondo y 180° en primer plano). */
export function ringPosition(deg: number, radius: number, height: number): [number, number, number] {
  return [round4(radius * Math.sin(deg * RAD)), height, round4(-radius * Math.cos(deg * RAD))];
}

export function domainAngle(index: number): number {
  return LAYOUT.startAngleDeg + index * LAYOUT.stepDeg;
}

/** Ángulo de un agente dentro de su dominio: centrado si es el único, repartido
 * a ambos lados si son varios. */
export function agentAngle(domainIndex: number, indexInDomain: number, countInDomain: number): number {
  const center = domainAngle(domainIndex);
  if (countInDomain <= 1) return center;
  const offset = (indexInDomain - (countInDomain - 1) / 2) * LAYOUT.agentSpreadDeg * 2;
  return center + offset;
}

// --- Estado de cada nodo --------------------------------------------------------------

const STATUS_FROM_REGISTRY: Record<string, NodeStatus> = {
  AVAILABLE: "available",
  BUSY: "running",
  WAITING: "waiting",
  OFFLINE: "inactive",
  ERROR: "error",
};

/** Gravedad de cada estado: la del dominio es la peor de sus agentes. */
const SEVERITY: Record<NodeStatus, number> = {
  error: 5,
  blocked: 4,
  waiting: 3,
  running: 2,
  available: 1,
  inactive: 0,
};

export function worstStatus(statuses: NodeStatus[]): NodeStatus {
  if (statuses.length === 0) return "inactive";
  return statuses.reduce((worst, status) => (SEVERITY[status] > SEVERITY[worst] ? status : worst), statuses[0]);
}

/** Evidencia de la decisión del CEO por capacidad del agente que la produce. */
const EVIDENCE_BY_CAPABILITY: Record<string, string> = {
  market_validation: "product_validation",
  supplier_sourcing: "supplier_sourcing",
  financial_validation: "finance_validation",
  legal_validation: "legal_validation",
};

/** Estado del núcleo a partir de la decisión real del CEO. */
export function coreStatus(decision: Decision | null): NodeStatus {
  if (!decision) return "available";
  if (decision.status === "GO") return "running";
  if (decision.status === "NO_GO") return "error";
  return "waiting";
}

// --- Construcción del grafo -----------------------------------------------------------

export interface NexusInput {
  agents: Agent[];
  executions: AgentExecution[];
  decision: Decision | null;
  now: number;
}

interface AgentSlot {
  id: string;
  label: string;
  domain: DomainKey;
  agent?: Agent;
}

/** Los agentes del registro repartidos en sus dominios, en el orden de los
 * dominios. Si el registro está vacío se usa el roster canónico de la
 * especificación, marcado como demostración. */
export function agentSlots(agents: Agent[]): AgentSlot[] {
  if (agents.length === 0) {
    return CANONICAL_AGENTS.map((entry) => ({ id: entry.id, label: entry.label, domain: entry.domain }));
  }
  const byDomain = new Map<DomainKey, AgentSlot[]>();
  for (const agent of agents) {
    const team = teamOf(agent.role);
    const domain = (DOMAINS as readonly string[]).includes(team) ? (team as DomainKey) : "Operaciones";
    byDomain.set(domain, [...(byDomain.get(domain) ?? []), { id: agent.id, label: agent.name, domain, agent }]);
  }
  return DOMAINS.flatMap((domain) => byDomain.get(domain) ?? []);
}

function agentStatusOf(slot: AgentSlot, decision: Decision | null): { status: NodeStatus; isDemo: boolean } {
  if (!slot.agent) return { status: "available", isDemo: true };
  const registry = STATUS_FROM_REGISTRY[slot.agent.status] ?? "available";
  if (!decision) return { status: registry, isDemo: false };

  const source = slot.agent.capabilities.map((capability) => EVIDENCE_BY_CAPABILITY[capability]).find(Boolean);
  if (!source) return { status: registry, isDemo: false };
  const evidence = decision.evidence.find((item) => item.source === source);
  if (!evidence) return { status: "waiting", isDemo: false };

  // El veto financiero y el NO_GO legal son bloqueos reales de la decisión.
  const vetoed = Boolean(evidence.data?.finance_veto) || evidence.data?.legal_status === "NO_GO";
  return { status: vetoed ? "blocked" : "running", isDemo: false };
}

export function buildGraph(input: NexusInput): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const { agents, executions, decision, now } = input;
  const slots = agentSlots(agents);
  const dayStart = now - (now % 86_400_000);
  const byAgent = new Map<string, AgentExecution[]>();
  for (const execution of executions) {
    byAgent.set(execution.agent_id, [...(byAgent.get(execution.agent_id) ?? []), execution]);
  }

  const agentNodes: GraphNode[] = [];
  const domainStatuses = new Map<DomainKey, NodeStatus[]>();

  for (const domain of DOMAINS) {
    const domainIndex = DOMAINS.indexOf(domain);
    const own = slots.filter((slot) => slot.domain === domain);
    own.forEach((slot, indexInDomain) => {
      const { status, isDemo } = agentStatusOf(slot, decision);
      const runs = byAgent.get(slot.id) ?? [];
      const failures = runs.filter((run) => !run.success).length;
      const tasks = DEMO_TASKS[domain];
      const lastAt = runs.length > 0 ? Math.max(...runs.map((run) => parseUtc(run.created_at))) : undefined;
      agentNodes.push({
        id: slot.id,
        type: "agent",
        label: slot.label,
        domain,
        position: ringPosition(agentAngle(domainIndex, indexInDomain, own.length), LAYOUT.agentRadius, LAYOUT.agentHeight),
        status,
        description: DOMAIN_DESCRIPTION[domain],
        projectName: decision ? decision.project_id : DEMO_PROJECT.code,
        task: status === "running" ? tasks[demoTaskIndex(slot.id, tasks.length)] : undefined,
        progress: status === "running" ? demoProgress(slot.id) : undefined,
        lastActivityAt: lastAt,
        metrics: {
          runs: runs.length,
          successRate: runs.length > 0 ? (runs.length - failures) / runs.length : undefined,
          latencyMs: runs.length > 0 ? runs.reduce((sum, run) => sum + run.duration_ms, 0) / runs.length : undefined,
          costToday: round2(runs.filter((run) => parseUtc(run.created_at) >= dayStart).length * (COST_PER_RUN[domain] ?? COST_PER_RUN.Otros)),
          evaluationScore: demoEvaluation(slot.id),
        },
        isDemo,
      });
      domainStatuses.set(domain, [...(domainStatuses.get(domain) ?? []), status]);
    });
  }

  const domainNodes: GraphNode[] = DOMAINS.map((domain, index) => ({
    id: `domain-${index}`,
    type: "domain" as const,
    label: domain,
    domain,
    position: ringPosition(domainAngle(index), LAYOUT.domainRadius, LAYOUT.domainHeight),
    status: worstStatus(domainStatuses.get(domain) ?? []),
    description: DOMAIN_DESCRIPTION[domain],
    isDemo: false,
  }));

  const core: GraphNode = {
    id: CORE_ID,
    type: "core",
    label: "Decision Engine",
    position: [0, LAYOUT.coreHeight, 0],
    status: coreStatus(decision),
    description: "Núcleo de inteligencia: procesa la información, evalúa opciones y coordina la ejecución.",
    projectName: decision ? decision.project_id : DEMO_PROJECT.code,
    progress: decision ? undefined : DEMO_PROJECT.progress,
    metrics: { latencyMs: DEMO_CORE_METRICS.latencyMs },
    isDemo: !decision,
  };

  const ceo: GraphNode = {
    id: CEO_ID,
    type: "ceo",
    label: "CEO",
    position: [0, LAYOUT.ceoHeight, 0],
    status: decision ? "running" : "available",
    description: "Orquestador del sistema. Coordina agentes, valida decisiones y supervisa la ejecución global.",
    isDemo: false,
  };

  const nodes = [ceo, core, ...domainNodes, ...agentNodes];
  return { nodes, edges: buildEdges(nodes) };
}

const round2 = (value: number) => Math.round(value * 100) / 100;

/** Jerarquía permanente (CEO → núcleo → dominios → agentes) más las conexiones
 * contextuales: flujo de los agentes que están ejecutando, dependencia de los
 * handoffs entre dominios e incidencia de los que están bloqueados o en error. */
export function buildEdges(nodes: GraphNode[]): GraphEdge[] {
  const domains = nodes.filter((node) => node.type === "domain");
  const agents = nodes.filter((node) => node.type === "agent");
  const domainIdOf = new Map(domains.map((node) => [node.domain!, node.id] as const));

  const edges: GraphEdge[] = [
    { id: "ceo-core", source: CEO_ID, target: CORE_ID, type: "hierarchy", active: true, status: "normal" },
  ];

  for (const domain of domains) {
    edges.push({
      id: `core-${domain.id}`,
      source: CORE_ID,
      target: domain.id,
      type: "hierarchy",
      active: domain.status === "running",
      status: domain.status === "error" || domain.status === "blocked" ? "error" : "normal",
    });
  }

  for (const agent of agents) {
    const domainId = domainIdOf.get(agent.domain!);
    if (!domainId) continue;
    edges.push({
      id: `${domainId}-${agent.id}`,
      source: domainId,
      target: agent.id,
      type: "hierarchy",
      active: agent.status === "running",
      status: agent.status === "error" || agent.status === "blocked" ? "error" : "normal",
    });
    if (agent.status === "running") {
      edges.push({ id: `flow-${agent.id}`, source: agent.id, target: CORE_ID, type: "flow", active: true, status: "normal" });
    }
    if (agent.status === "blocked" || agent.status === "error") {
      edges.push({
        id: `incident-${agent.id}`,
        source: agent.id,
        target: CORE_ID,
        type: "incident",
        active: true,
        status: agent.status === "error" ? "error" : "warning",
      });
    }
  }

  // Handoffs entre dominios: dependencia de demostración, solo con los dos extremos presentes.
  for (const [from, to] of DEMO_HANDOFFS) {
    const source = domainIdOf.get(from as DomainKey);
    const target = domainIdOf.get(to as DomainKey);
    if (!source || !target) continue;
    edges.push({ id: `handoff-${source}-${target}`, source, target, type: "dependency", active: false, status: "normal" });
  }

  return edges;
}

// --- Modos ----------------------------------------------------------------------------

export interface ModeView {
  /** Aristas que se dibujan en este modo. */
  edges: GraphEdge[];
  /** Nodos atenuados: no aportan nada a lo que el modo quiere enseñar. */
  dimmed: Set<string>;
}

const INCIDENT_STATUSES: NodeStatus[] = ["blocked", "error", "waiting"];

/** Qué se ve en cada modo (§16–18). Arquitectura enseña la estructura y calla el
 * tráfico; Ejecución resalta lo que está pasando; Incidencias, lo que está
 * atascado. Ninguno esconde la jerarquía: sin ella el grafo deja de leerse. */
export function applyMode(nodes: GraphNode[], edges: GraphEdge[], mode: GraphMode): ModeView {
  if (mode === "architecture") {
    return { edges: edges.filter((edge) => edge.type === "hierarchy"), dimmed: new Set() };
  }

  if (mode === "execution") {
    const active = new Set(nodes.filter((node) => node.status === "running").map((node) => node.id));
    const dimmed = new Set(
      nodes
        .filter((node) => node.type === "agent" && node.status !== "running")
        .map((node) => node.id),
    );
    return {
      edges: edges.filter((edge) => edge.type !== "incident" && (edge.type !== "dependency" || active.has(edge.source) || active.has(edge.target))),
      dimmed,
    };
  }

  const affected = new Set(nodes.filter((node) => INCIDENT_STATUSES.includes(node.status)).map((node) => node.id));
  const dimmed = new Set(
    nodes.filter((node) => (node.type === "agent" || node.type === "domain") && !affected.has(node.id)).map((node) => node.id),
  );
  return {
    edges: edges.filter((edge) => edge.type === "incident" || edge.type === "dependency" || edge.status !== "normal" || edge.type === "hierarchy"),
    dimmed,
  };
}

/** Los nodos conectados directamente con `id` (para el foco al seleccionar). */
export function relatedIds(edges: GraphEdge[], id: string | null): Set<string> {
  if (!id) return new Set();
  const related = new Set<string>([id]);
  for (const edge of edges) {
    if (edge.source === id) related.add(edge.target);
    if (edge.target === id) related.add(edge.source);
  }
  return related;
}

// --- HUD ------------------------------------------------------------------------------

export interface HudMetrics {
  coreStatus: NodeStatus;
  activeEvents: number;
  activeEventsAreDemo: boolean;
  activeAgents: number;
  totalAgents: number;
  /** Latencia media real de las ejecuciones; null si no hay ninguna. */
  latencyMs: number | null;
  projectName: string;
  projectIsReal: boolean;
  progress: number;
  progressIsReal: boolean;
}

export function hudMetrics(nodes: GraphNode[], executions: AgentExecution[], decision: Decision | null): HudMetrics {
  const agents = nodes.filter((node) => node.type === "agent");
  const running = agents.filter((node) => node.status === "running").length;
  const core = nodes.find((node) => node.id === CORE_ID);
  const latency = executions.length > 0 ? executions.reduce((sum, run) => sum + run.duration_ms, 0) / executions.length : null;
  const evidence = decision?.evidence.length ?? 0;
  return {
    coreStatus: core?.status ?? "available",
    activeEvents: evidence > 0 ? evidence : running > 0 ? running : DEMO_CORE_METRICS.activeEvents,
    activeEventsAreDemo: evidence === 0 && running === 0,
    activeAgents: running,
    totalAgents: agents.length,
    latencyMs: latency,
    projectName: decision ? decision.project_id : DEMO_PROJECT.code,
    projectIsReal: decision !== null,
    progress: decision?.confidence ?? DEMO_PROJECT.progress,
    progressIsReal: decision?.confidence != null,
  };
}
