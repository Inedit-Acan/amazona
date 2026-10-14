import type { Agent, AgentExecution, Decision } from "./api.ts";
import { teamOf } from "./agents.ts";
import { CEO_ANCHOR, zoneAnchor, type Vec3 } from "./decision-engine.ts";
import { parseUtc } from "./dates.ts";
import { COST_PER_RUN } from "./demo/agents.ts";
import { readAgentStatus, type AgentStatusReading } from "./agent-status.ts";
import {
  DOMAIN_AGENT_ICON_KEYS,
  DOMAIN_ICON_KEY,
  DEMO_HANDOFFS,
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
// CEO → Decision Engine → 8 dominios → los agentes del registro. El layout es
// DETERMINISTA y estable entre sesiones: las posiciones se calculan aquí, no las
// decide un force-graph. Real: los agentes del registro con su estado, el log de
// ejecuciones y la decisión del CEO con sus evidencias. Demo
// (lib/demo/neural-nexus.ts): la tarea en curso de un agente que ejecuta, su
// progreso y los handoffs entre dominios (se retiran en el Commit 5 de M47).
//
// M47 · Commit 1: este módulo ya NO inventa nada para llenar un hueco. Sin
// registro de agentes no hay agentes (antes salía un roster canónico de 13
// «Disponible»); sin decisión no hay proyecto ni progreso ni eventos (antes salían
// «AMZ-2026-003», «68 %» y «3 eventos»); sin ejecuciones leídas no hay métricas de
// ejecución. Y un estado de registro que el backend no envía no se traduce a uno
// conocido: es `unknown` (ver lib/agent-status.ts).

export type NodeType = "ceo" | "core" | "domain" | "agent";
/** Estado VISUAL de un nodo. No es `AgentStatus` (lo que dice el registro) ni `ReadState` (si se pudo leer): es la
 * categoría con la que se dibuja, derivada de lo anterior y, en los agentes con evidencia, de la decisión del CEO.
 * `degraded` = el registro dice `DEGRADED` (funcionamiento parcial; NO es `waiting`, que es esperar legítimamente).
 * `unknown` = el registro envió un texto que no es ninguno de sus estados. */
export type NodeStatus = "available" | "running" | "waiting" | "blocked" | "degraded" | "error" | "inactive" | "unknown";
export type GraphMode = "architecture" | "execution" | "incidents";
export type EdgeType = "hierarchy" | "flow" | "dependency" | "incident";

export const CORE_ID = "core";
export const CEO_ID = "ceo";

export const STATUS_LABEL: Record<NodeStatus, string> = {
  available: "Disponible",
  running: "Ejecutando",
  waiting: "Esperando",
  blocked: "Bloqueado",
  degraded: "Degradado",
  error: "Error",
  inactive: "Inactivo",
  unknown: "Desconocido",
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
  /** Solo el núcleo (§28 de la especificación del Decision Engine): eventos en
   * curso, handoffs entre dominios y puertas humanas. */
  activeEvents?: number;
  handoffs?: number;
  humanGates?: number;
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
  /** Clave del icono; la capa visual la traduce a un componente. */
  icon: string;
  projectName?: string;
  task?: string;
  progress?: number;
  lastActivityAt?: number;
  metrics?: NodeMetrics;
  /** El estado o la tarea del nodo son de demostración. */
  isDemo: boolean;
  /** Lo que dice el registro de este agente, sin traducir (solo agentes). El estado visual (`status`) puede diferir
   * cuando la decisión del CEO lo matiza; este campo es siempre lo que el backend devolvió. */
  registry?: AgentStatusReading;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  active: boolean;
  status: "normal" | "warning" | "error";
  /** Punto por el que la conexión entra en el Decision Engine, cuando uno de
   * sus extremos es el núcleo. Cada dominio tiene el suyo: las conexiones no
   * convergen todas en el mismo sitio (§13.2 y §14 de la especificación del
   * Decision Engine). */
  anchor?: Vec3;
}

// --- Layout determinista --------------------------------------------------------------

/** Radios de cada anillo y altura de cada nivel. Las alturas están separadas de
 * verdad —CEO arriba, dominios en un plano intermedio alto, núcleo en el centro
 * y agentes en un plano exterior más bajo—: la profundidad la da la posición, no
 * la niebla ni el brillo (corrección visual §3.7 y §29). */
export const LAYOUT = {
  ceoHeight: 4.4,
  coreHeight: 0,
  domainRadius: 3.5,
  domainHeight: 0.95,
  agentRadius: 6.5,
  agentHeight: -1.5,
  /** El anillo arranca girado para dejar libre la vertical del CEO y para que
   * cada dominio caiga del lado que le asigna el mapeo dominio → cerebro
   * (especificación del Decision Engine §14): Investigación, Abastecimiento,
   * Comercio y Marketing a la izquierda; Economía, Legal, Finanzas y
   * Operaciones a la derecha. Es también el reparto de la imagen de
   * referencia. */
  startAngleDeg: -67.5,
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

/** Cómo se dibuja cada estado REAL del registro. Los siete de `AgentStatus` y nada más: `OFFLINE` y `ERROR` no existen
 * en el backend y no se mapean. Un texto desconocido es `unknown`, nunca `available`. */
export function nodeStatusOfRegistry(reading: AgentStatusReading): NodeStatus {
  if (reading.kind === "unknown") return "unknown";
  switch (reading.status) {
    case "AVAILABLE":
      return "available";
    case "BUSY":
      return "running";
    case "WAITING":
      return "waiting";
    case "BLOCKED":
      return "blocked";
    case "DEGRADED":
      return "degraded";
    case "DISABLED":
      return "inactive";
    case "FAILED":
      return "error";
  }
}

/** Gravedad de cada estado: la del dominio es la peor de sus agentes. Lo que no se sabe (`unknown`) pesa más que lo
 * que va bien: un dominio con un agente cuyo estado no se reconoce no puede enseñarse como sano. */
const SEVERITY: Record<NodeStatus, number> = {
  error: 7,
  blocked: 6,
  degraded: 5,
  unknown: 4,
  waiting: 3,
  running: 2,
  available: 1,
  inactive: 0,
};

/** Estados del registro que la decisión del CEO NO puede suavizar: si el registro dice que el agente no está bien, el
 * hecho de que aparezca en la evidencia de una decisión no lo convierte en «ejecutando». */
const REGISTRY_OVERRIDES_DECISION: ReadonlySet<NodeStatus> = new Set<NodeStatus>(["blocked", "degraded", "error", "inactive", "unknown"]);

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
  /** Los agentes del registro (lectura válida). Vacío = sin agentes: el grafo no los inventa. */
  agents: Agent[];
  /** El log de ejecuciones. `null` = NO se pudo leer: nada de lo derivado de las ejecuciones se calcula (ni un 0). `[]` =
   * el backend dijo que no hay ninguna. */
  executions: AgentExecution[] | null;
  decision: Decision | null;
  now: number;
}

interface AgentSlot {
  id: string;
  label: string;
  domain: DomainKey;
  agent: Agent;
}

/** Los agentes del registro repartidos en sus dominios, en el orden de los dominios. Un registro vacío da cero
 * agentes: no hay roster de relleno. */
export function agentSlots(agents: Agent[]): AgentSlot[] {
  const byDomain = new Map<DomainKey, AgentSlot[]>();
  for (const agent of agents) {
    const team = teamOf(agent.role);
    const domain = (DOMAINS as readonly string[]).includes(team) ? (team as DomainKey) : "Operaciones";
    byDomain.set(domain, [...(byDomain.get(domain) ?? []), { id: agent.id, label: agent.name, domain, agent }]);
  }
  return DOMAINS.flatMap((domain) => byDomain.get(domain) ?? []);
}

function agentStatusOf(slot: AgentSlot, decision: Decision | null): { status: NodeStatus; registry: AgentStatusReading } {
  const registry = readAgentStatus(slot.agent.status);
  const fromRegistry = nodeStatusOfRegistry(registry);
  if (!decision || REGISTRY_OVERRIDES_DECISION.has(fromRegistry)) return { status: fromRegistry, registry };

  const source = slot.agent.capabilities.map((capability) => EVIDENCE_BY_CAPABILITY[capability]).find(Boolean);
  if (!source) return { status: fromRegistry, registry };
  const evidence = decision.evidence.find((item) => item.source === source);
  if (!evidence) return { status: "waiting", registry };

  // El veto financiero y el NO_GO legal son bloqueos reales de la decisión.
  const vetoed = Boolean(evidence.data?.finance_veto) || evidence.data?.legal_status === "NO_GO";
  return { status: vetoed ? "blocked" : "running", registry };
}

/** Latencia media de un log de ejecuciones; `null` si no se pudo leer o está vacío. Nunca un número de relleno. */
export function meanLatencyMs(executions: AgentExecution[] | null): number | null {
  if (executions === null || executions.length === 0) return null;
  return executions.reduce((sum, run) => sum + run.duration_ms, 0) / executions.length;
}

export function buildGraph(input: NexusInput): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const { agents, executions, decision, now } = input;
  const slots = agentSlots(agents);
  const dayStart = now - (now % 86_400_000);
  const byAgent = new Map<string, AgentExecution[]>();
  for (const execution of executions ?? []) {
    byAgent.set(execution.agent_id, [...(byAgent.get(execution.agent_id) ?? []), execution]);
  }

  const agentNodes: GraphNode[] = [];
  const domainStatuses = new Map<DomainKey, NodeStatus[]>();

  for (const domain of DOMAINS) {
    const domainIndex = DOMAINS.indexOf(domain);
    const own = slots.filter((slot) => slot.domain === domain);
    own.forEach((slot, indexInDomain) => {
      const { status, registry } = agentStatusOf(slot, decision);
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
        icon: DOMAIN_AGENT_ICON_KEYS[domain][indexInDomain] ?? DOMAIN_ICON_KEY[domain],
        projectName: decision ? decision.project_id : undefined,
        task: status === "running" ? tasks[demoTaskIndex(slot.id, tasks.length)] : undefined,
        progress: status === "running" ? demoProgress(slot.id) : undefined,
        lastActivityAt: lastAt,
        // Sin el log de ejecuciones leído NO hay métricas de ejecución: ni «0 ejecuciones» ni «0 €» (eso sería ERROR → 0).
        metrics:
          executions === null
            ? { evaluationScore: demoEvaluation(slot.id) }
            : {
                runs: runs.length,
                successRate: runs.length > 0 ? (runs.length - failures) / runs.length : undefined,
                latencyMs: runs.length > 0 ? runs.reduce((sum, run) => sum + run.duration_ms, 0) / runs.length : undefined,
                costToday: round2(runs.filter((run) => parseUtc(run.created_at) >= dayStart).length * (COST_PER_RUN[domain] ?? COST_PER_RUN.Otros)),
                evaluationScore: demoEvaluation(slot.id),
              },
        isDemo: false,
        registry,
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
    icon: DOMAIN_ICON_KEY[domain],
    isDemo: false,
  }));

  const core: GraphNode = {
    id: CORE_ID,
    type: "core",
    label: "Decision Engine",
    position: [0, LAYOUT.coreHeight, 0],
    status: coreStatus(decision),
    description: "Núcleo de inteligencia: procesa la información, evalúa opciones y coordina la ejecución.",
    icon: "core",
    projectName: decision ? decision.project_id : undefined,
    // Solo lo que existe: los eventos son las evidencias de la decisión y la latencia es la media de las ejecuciones
    // leídas. Los handoffs y las puertas humanas no tienen fuente en el backend: no se enseñan.
    metrics: {
      latencyMs: meanLatencyMs(executions) ?? undefined,
      activeEvents: decision ? decision.evidence.length : undefined,
    },
    isDemo: false,
  };

  const ceo: GraphNode = {
    id: CEO_ID,
    type: "ceo",
    label: "CEO",
    position: [0, LAYOUT.ceoHeight, 0],
    status: decision ? "running" : "available",
    description: "Orquestador del sistema. Coordina agentes, valida decisiones y supervisa la ejecución global.",
    icon: "ceo",
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

  // Zona neural de cada dominio: la conexión entra por ahí, y por ahí entran
  // también el flujo y las incidencias de sus agentes (§15.1).
  const anchorOf = new Map(DOMAINS.map((domain, index) => [domain, zoneAnchor(domainAngle(index))] as const));

  const edges: GraphEdge[] = [
    { id: "ceo-core", source: CEO_ID, target: CORE_ID, type: "hierarchy", active: true, status: "normal", anchor: CEO_ANCHOR },
  ];

  for (const domain of domains) {
    edges.push({
      id: `core-${domain.id}`,
      source: CORE_ID,
      target: domain.id,
      type: "hierarchy",
      active: domain.status === "running",
      status: domain.status === "error" || domain.status === "blocked" ? "error" : "normal",
      anchor: anchorOf.get(domain.domain!),
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
      edges.push({
        id: `flow-${agent.id}`,
        source: agent.id,
        target: CORE_ID,
        type: "flow",
        active: true,
        status: "normal",
        anchor: anchorOf.get(agent.domain!),
      });
    }
    if (agent.status === "blocked" || agent.status === "error" || agent.status === "degraded" || agent.status === "unknown") {
      edges.push({
        id: `incident-${agent.id}`,
        source: agent.id,
        target: CORE_ID,
        type: "incident",
        active: true,
        status: agent.status === "error" ? "error" : "warning",
        anchor: anchorOf.get(agent.domain!),
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

// --- Zonas neurales -------------------------------------------------------------------

export interface NeuralZone {
  id: string;
  label: DomainKey;
  /** Ángulo del dominio en el anillo; de él salen la zona y su ruta neural. */
  angle: number;
  anchor: Vec3;
  status: NodeStatus;
}

/** Las ocho zonas del cerebro con el estado del dominio que entra por cada una.
 * Es lo que permite encender la ruta del dominio que está ejecutando y resaltar
 * SOLO la zona afectada cuando uno se bloquea o falla, en vez de teñir el
 * cerebro entero (§26 de la especificación del Decision Engine). */
export function neuralZones(nodes: GraphNode[]): NeuralZone[] {
  return DOMAINS.map((domain, index) => {
    const node = nodes.find((item) => item.type === "domain" && item.domain === domain);
    const angle = domainAngle(index);
    return {
      id: node?.id ?? `domain-${index}`,
      label: domain,
      angle,
      anchor: zoneAnchor(angle),
      status: node?.status ?? "inactive",
    };
  });
}

// --- Modos ----------------------------------------------------------------------------

export interface ModeView {
  /** Aristas que se dibujan en este modo. */
  edges: GraphEdge[];
  /** Nodos atenuados: no aportan nada a lo que el modo quiere enseñar. */
  dimmed: Set<string>;
}

const INCIDENT_STATUSES: NodeStatus[] = ["blocked", "error", "degraded", "unknown", "waiting"];

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

/** Cada cifra del HUD es un dato real o `null` («sin dato»): ninguna lleva un valor de relleno ni una etiqueta «demo». */
export interface HudMetrics {
  coreStatus: NodeStatus;
  /** Las evidencias de la decisión del CEO; `null` si no hay decisión. */
  activeEvents: number | null;
  activeAgents: number;
  totalAgents: number;
  /** Latencia media de las ejecuciones; `null` si el log no se pudo leer o está vacío. */
  latencyMs: number | null;
  /** El proyecto de la decisión del CEO; `null` si no hay decisión. */
  projectName: string | null;
  /** La confianza de la decisión (0–1); `null` si no hay decisión o no trae confianza. */
  progress: number | null;
}

export function hudMetrics(nodes: GraphNode[], executions: AgentExecution[] | null, decision: Decision | null): HudMetrics {
  const agents = nodes.filter((node) => node.type === "agent");
  const running = agents.filter((node) => node.status === "running").length;
  const core = nodes.find((node) => node.id === CORE_ID);
  return {
    coreStatus: core?.status ?? "available",
    activeEvents: decision ? decision.evidence.length : null,
    activeAgents: running,
    totalAgents: agents.length,
    latencyMs: meanLatencyMs(executions),
    projectName: decision ? decision.project_id : null,
    progress: decision?.confidence ?? null,
  };
}
