import type { Agent, AgentExecution } from "./api.ts";
import { parseUtc } from "./dates.ts";
import {
  ALERT_THRESHOLDS,
  COST_PER_RUN,
  CURRENT_TASKS,
  DEMO_TOOLS,
  DEMO_VERSION_NOTES,
  ROLE_DESCRIPTIONS,
  demoEvalScore,
  demoTaskIndex,
  demoTaskProgress,
} from "./demo/agents.ts";
import { TEAMS, agentStats, executionsByAgent, teamOf, type Team } from "./agents.ts";

// Vista de la pantalla de Agentes (mockup docs/design/agentes.png). Real: el
// registro de agentes (nombre, rol, capacidades, estado, fiabilidad, versión) y
// el log de ejecuciones (éxito, latencia, fecha, capacidad), de donde salen la
// tasa de éxito, la latencia, la actividad y la distribución por equipo. Demo
// (lib/demo/agents.ts): la descripción, la evaluación, el coste por ejecución
// (el `cost_profile` del backend es 0), la tarea en curso, las herramientas y el
// histórico de versiones.

const DAY_MS = 86_400_000;
const round2 = (value: number) => Math.round(value * 100) / 100;

export type AgentActivity = "running" | "available" | "waiting" | "offline";

export const ACTIVITY_LABEL: Record<AgentActivity, string> = {
  running: "Ejecutando",
  available: "Disponible",
  waiting: "En espera",
  offline: "Fuera de servicio",
};

export interface AgentCardView {
  id: string;
  name: string;
  role: string;
  team: Team;
  description: string;
  activity: AgentActivity;
  capabilities: string[];
  version: string;
  /** Fracción; null si el agente no tiene ejecuciones registradas. */
  successRate: number | null;
  evalScore: number;
  avgLatencyMs: number | null;
  runs: number;
  runsToday: number;
  costToday: number;
  lastActivityAt: number | null;
  /** Tarea en curso: solo cuando el agente está ejecutando. */
  currentTask: string | null;
  taskProgress: number | null;
  tools: string[];
}

const ACTIVITY_BY_STATUS: Record<string, AgentActivity> = {
  AVAILABLE: "available",
  BUSY: "running",
  WAITING: "waiting",
  OFFLINE: "offline",
};

/** Una tarjeta por agente: lo medible sale del log de ejecuciones y el resto de
 * la demostración. `now` fija el día para el coste de hoy. */
export function agentCards(agents: Agent[], executions: AgentExecution[], now: number): AgentCardView[] {
  const byAgent = executionsByAgent(executions);
  const dayStart = now - (now % DAY_MS);
  return agents.map((agent) => {
    const own = byAgent.get(agent.id) ?? [];
    const stats = agentStats(own);
    const team = teamOf(agent.role);
    const runsToday = own.filter((e) => parseUtc(e.created_at) >= dayStart).length;
    const activity = ACTIVITY_BY_STATUS[agent.status] ?? "available";
    const tasks = CURRENT_TASKS[team] ?? CURRENT_TASKS.Otros;
    return {
      id: agent.id,
      name: agent.name,
      role: agent.role,
      team,
      description: ROLE_DESCRIPTIONS[agent.role] ?? "Agente especialista de AMAZONA.",
      activity,
      capabilities: agent.capabilities,
      version: agent.version,
      successRate: stats.successRate,
      evalScore: demoEvalScore(agent.id),
      avgLatencyMs: stats.avgLatencyMs,
      runs: stats.runs,
      runsToday,
      costToday: round2(runsToday * (COST_PER_RUN[team] ?? COST_PER_RUN.Otros)),
      lastActivityAt: stats.lastActivity ? stats.lastActivity.getTime() : null,
      currentTask: activity === "running" ? tasks[demoTaskIndex(agent.id, tasks.length)] : null,
      taskProgress: activity === "running" ? Math.round(demoTaskProgress(agent.id) * 100) / 100 : null,
      tools: DEMO_TOOLS[team] ?? DEMO_TOOLS.Otros,
    };
  });
}

export interface FleetKpis {
  registered: number;
  running: number;
  available: number;
  /** Éxito de las ejecuciones de los últimos `days` días; null sin ejecuciones. */
  successRate: number | null;
  costToday: number;
  alerts: number;
  criticalAlerts: number;
}

export function fleetKpis(cards: AgentCardView[], alerts: FleetAlert[]): FleetKpis {
  const withRuns = cards.filter((card) => card.successRate !== null);
  const runs = withRuns.reduce((sum, card) => sum + card.runs, 0);
  const successes = withRuns.reduce((sum, card) => sum + card.runs * (card.successRate ?? 0), 0);
  return {
    registered: cards.length,
    running: cards.filter((card) => card.activity === "running").length,
    available: cards.filter((card) => card.activity === "available").length,
    successRate: runs > 0 ? successes / runs : null,
    costToday: round2(cards.reduce((sum, card) => sum + card.costToday, 0)),
    alerts: alerts.length,
    criticalAlerts: alerts.filter((alert) => alert.level === "Alta").length,
  };
}

export interface UsagePoint {
  /** Días desde hoy (negativo hacia atrás). */
  offset: number;
  label: string;
  runs: number;
  cost: number;
}

/** Ejecuciones y coste por día de los últimos `days` días. */
export function usageByDay(agents: Agent[], executions: AgentExecution[], days: number, now: number): UsagePoint[] {
  const dayStart = now - (now % DAY_MS);
  const costOf = new Map(agents.map((agent) => [agent.id, COST_PER_RUN[teamOf(agent.role)] ?? COST_PER_RUN.Otros] as const));
  const points: UsagePoint[] = [];
  for (let offset = -(days - 1); offset <= 0; offset++) {
    const from = dayStart + offset * DAY_MS;
    const own = executions.filter((e) => {
      const at = parseUtc(e.created_at);
      return at >= from && at < from + DAY_MS;
    });
    points.push({
      offset,
      label: new Date(from).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" }),
      runs: own.length,
      cost: round2(own.reduce((sum, e) => sum + (costOf.get(e.agent_id) ?? COST_PER_RUN.Otros), 0)),
    });
  }
  return points;
}

/** Coste de hoy por agente, de mayor a menor (solo los que han ejecutado algo). */
export function costByAgent(cards: AgentCardView[]): { key: string; label: string; value: number }[] {
  return cards
    .filter((card) => card.costToday > 0)
    .map((card) => ({ key: card.id, label: card.name, value: card.costToday }))
    .sort((a, b) => b.value - a.value);
}

export interface FleetAlert {
  key: string;
  level: "Alta" | "Media";
  agent: string;
  message: string;
}

/** Alertas de la flota: error, latencia y coste desviado, sobre datos reales. */
export function fleetAlerts(cards: AgentCardView[]): FleetAlert[] {
  const alerts: FleetAlert[] = [];
  const active = cards.filter((card) => card.runs > 0);
  const averageCost = active.length ? active.reduce((sum, card) => sum + card.costToday, 0) / active.length : 0;

  for (const card of active) {
    const errorRate = 1 - (card.successRate ?? 1);
    if (errorRate > ALERT_THRESHOLDS.errorRate) {
      alerts.push({
        key: `${card.id}-error`,
        level: errorRate > ALERT_THRESHOLDS.errorRate * 3 ? "Alta" : "Media",
        agent: card.name,
        message: `Tasa de error ${(errorRate * 100).toLocaleString("es-ES", { maximumFractionDigits: 1 })} % en ${card.runs} ejecuciones`,
      });
    }
    if ((card.avgLatencyMs ?? 0) > ALERT_THRESHOLDS.latencyMs) {
      alerts.push({
        key: `${card.id}-latency`,
        level: "Media",
        agent: card.name,
        message: `Latencia media ${(card.avgLatencyMs! / 1000).toLocaleString("es-ES", { maximumFractionDigits: 1 })} s`,
      });
    }
    if (averageCost > 0 && card.costToday > averageCost * (1 + ALERT_THRESHOLDS.costSpread)) {
      alerts.push({
        key: `${card.id}-cost`,
        level: "Media",
        agent: card.name,
        message: `Coste ${(((card.costToday - averageCost) / averageCost) * 100).toLocaleString("es-ES", { maximumFractionDigits: 0 })} % sobre la media de la flota`,
      });
    }
  }
  return alerts.sort((a, b) => (a.level === b.level ? a.agent.localeCompare(b.agent, "es") : a.level === "Alta" ? -1 : 1));
}

export interface ActivityEntry {
  id: string;
  agent: string;
  team: Team;
  capability: string;
  success: boolean;
  durationMs: number;
  at: number;
  correlationId: string;
}

/** Últimas ejecuciones, de la más reciente a la más antigua. */
export function activityFeed(agents: Agent[], executions: AgentExecution[], limit: number): ActivityEntry[] {
  const byId = new Map(agents.map((agent) => [agent.id, agent] as const));
  return executions
    .map((execution) => {
      const agent = byId.get(execution.agent_id);
      return {
        id: execution.id,
        agent: agent?.name ?? execution.agent_id,
        team: agent ? teamOf(agent.role) : ("Otros" as Team),
        capability: execution.capability,
        success: execution.success,
        durationMs: execution.duration_ms,
        at: parseUtc(execution.created_at),
        correlationId: execution.correlation_id,
      };
    })
    .sort((a, b) => b.at - a.at)
    .slice(0, limit);
}

export interface VersionRow {
  agent: string;
  version: string;
  note: string;
  current: boolean;
}

/** Versión inmediatamente anterior a una `major.minor.patch`. */
export function previousVersion(version: string): string {
  const [major, minor, patch] = version.split(".").map((part) => Number.parseInt(part, 10) || 0);
  if (patch > 0) return `${major}.${minor}.${patch - 1}`;
  if (minor > 0) return `${major}.${minor - 1}.9`;
  if (major > 0) return `${major - 1}.9.9`;
  return version;
}

/** Versión actual (real) y las anteriores, de demostración. */
export function versionHistory(card: AgentCardView, depth = 3): VersionRow[] {
  const rows: VersionRow[] = [{ agent: card.name, version: card.version, note: "Versión en uso", current: true }];
  let version = card.version;
  for (let k = 1; k < depth; k++) {
    version = previousVersion(version);
    rows.push({ agent: card.name, version, note: DEMO_VERSION_NOTES[(k - 1) % DEMO_VERSION_NOTES.length], current: false });
  }
  return rows;
}

export type SortKey = "name" | "success" | "cost" | "runs";

export const SORT_LABELS: Record<SortKey, string> = {
  name: "Nombre (A-Z)",
  success: "Tasa de éxito",
  cost: "Coste de hoy",
  runs: "Ejecuciones",
};

export function sortCards(cards: AgentCardView[], key: SortKey): AgentCardView[] {
  const copy = [...cards];
  if (key === "name") return copy.sort((a, b) => a.name.localeCompare(b.name, "es"));
  if (key === "success") return copy.sort((a, b) => (b.successRate ?? -1) - (a.successRate ?? -1));
  if (key === "cost") return copy.sort((a, b) => b.costToday - a.costToday);
  return copy.sort((a, b) => b.runs - a.runs);
}

/** Filtro por equipo y texto (nombre, rol o capacidad). */
export function filterCards(cards: AgentCardView[], filters: { team?: string; query?: string }): AgentCardView[] {
  const query = (filters.query ?? "").trim().toLowerCase();
  return cards.filter((card) => {
    if (filters.team && filters.team !== "all" && card.team !== filters.team) return false;
    if (!query) return true;
    return `${card.name} ${card.role} ${card.capabilities.join(" ")}`.toLowerCase().includes(query);
  });
}

/** Agrupa las tarjetas por equipo, en el orden de los equipos y «Otros» al final. */
export function groupCards(cards: AgentCardView[]): { team: Team; agents: AgentCardView[] }[] {
  const groups = new Map<Team, AgentCardView[]>();
  for (const card of cards) groups.set(card.team, [...(groups.get(card.team) ?? []), card]);
  const order: Team[] = [...TEAMS, "Otros"];
  return order.flatMap((team) => (groups.has(team) ? [{ team, agents: groups.get(team)! }] : []));
}
