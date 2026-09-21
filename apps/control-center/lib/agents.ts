import type { Agent, AgentExecution } from "./api.ts";
import { parseUtc } from "./dates.ts";

// Los agentes y sus ejecuciones salen del registro y del log de ejecuciones del
// CEO (AgentExecutionLog). No hay evaluaciones, costes medidos, tokens, versiones
// históricas ni herramientas/permisos. Este módulo solo agrupa y resume lo que ya
// devolvió el backend.

export const TEAMS = [
  "Investigación",
  "Abastecimiento",
  "Economía",
  "Legal",
  "Comercio",
  "Marketing",
  "Operaciones",
  "Finanzas",
] as const;

export type Team = (typeof TEAMS)[number] | "Otros";

/** Equipo de cada rol del registro, siguiendo los equipos de la spec (parte 2 §6.2).
 * El backend no guarda el equipo: es una clasificación de presentación por `role`. */
const TEAM_BY_ROLE: Record<string, Team> = {
  product: "Investigación",
  research: "Investigación",
  supplier: "Abastecimiento",
  sourcing: "Abastecimiento",
  finance: "Economía",
  economics: "Economía",
  legal: "Legal",
  legal_compliance: "Legal",
  ecommerce: "Comercio",
  marketplace: "Comercio",
  marketing: "Marketing",
  operations: "Operaciones",
  cfo: "Finanzas",
};

export function teamOf(role: string): Team {
  return TEAM_BY_ROLE[role] ?? "Otros";
}

/** Agentes agrupados por equipo, en el orden de la spec y con «Otros» al final;
 * los equipos sin agentes no aparecen. */
export function groupByTeam<T extends Pick<Agent, "role" | "name">>(agents: T[]): { team: Team; agents: T[] }[] {
  const groups = new Map<Team, T[]>();
  for (const agent of agents) {
    const team = teamOf(agent.role);
    groups.set(team, [...(groups.get(team) ?? []), agent]);
  }
  const order: Team[] = [...TEAMS, "Otros"];
  return order.flatMap((team) => {
    const list = groups.get(team);
    return list ? [{ team, agents: [...list].sort((a, b) => a.name.localeCompare(b.name, "es")) }] : [];
  });
}

export interface AgentStats {
  runs: number;
  failures: number;
  /** Fracción de ejecuciones correctas; null sin ejecuciones. */
  successRate: number | null;
  avgLatencyMs: number | null;
  lastActivity: Date | null;
}

export function agentStats(executions: Pick<AgentExecution, "success" | "duration_ms" | "created_at">[]): AgentStats {
  const runs = executions.length;
  const failures = executions.filter((e) => !e.success).length;
  return {
    runs,
    failures,
    successRate: runs > 0 ? (runs - failures) / runs : null,
    avgLatencyMs: runs > 0 ? executions.reduce((sum, e) => sum + e.duration_ms, 0) / runs : null,
    lastActivity: runs > 0 ? new Date(Math.max(...executions.map((e) => parseUtc(e.created_at)))) : null,
  };
}

/** Las ejecuciones de cada agente, por `agent_id`. */
export function executionsByAgent<T extends Pick<AgentExecution, "agent_id">>(executions: T[]): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const execution of executions) {
    map.set(execution.agent_id, [...(map.get(execution.agent_id) ?? []), execution]);
  }
  return map;
}

export interface FleetSummary {
  registered: number;
  available: number;
  busy: number;
  other: number;
  runs: number;
  successRate: number | null;
  avgLatencyMs: number | null;
  agentsWithErrors: number;
}

export function fleetSummary(agents: Pick<Agent, "id" | "status">[], executions: Pick<AgentExecution, "agent_id" | "success" | "duration_ms" | "created_at">[]): FleetSummary {
  const overall = agentStats(executions);
  const failedAgents = new Set(executions.filter((e) => !e.success).map((e) => e.agent_id));
  return {
    registered: agents.length,
    available: agents.filter((a) => a.status === "AVAILABLE").length,
    busy: agents.filter((a) => a.status === "BUSY").length,
    other: agents.filter((a) => a.status !== "AVAILABLE" && a.status !== "BUSY").length,
    runs: overall.runs,
    successRate: overall.successRate,
    avgLatencyMs: overall.avgLatencyMs,
    agentsWithErrors: agents.filter((a) => failedAgents.has(a.id)).length,
  };
}

export type ActivityWindow = "all" | "24h" | "7d" | "30d";

export const WINDOW_LABELS: Record<ActivityWindow, string> = {
  all: "Todo el histórico",
  "24h": "Últimas 24 h",
  "7d": "Últimos 7 días",
  "30d": "Últimos 30 días",
};

const WINDOW_MS: Record<Exclude<ActivityWindow, "all">, number> = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

export function withinWindow<T extends Pick<AgentExecution, "created_at">>(executions: T[], window: ActivityWindow, now: number): T[] {
  if (window === "all") return executions;
  return executions.filter((e) => now - parseUtc(e.created_at) <= WINDOW_MS[window]);
}

/** Ejecuciones por equipo del agente que las hizo (para la distribución de actividad). */
export function runsByTeam(
  agents: Pick<Agent, "id" | "role">[],
  executions: Pick<AgentExecution, "agent_id">[],
): { team: Team; runs: number }[] {
  const teamOfAgent = new Map(agents.map((a) => [a.id, teamOf(a.role)] as const));
  const totals = new Map<Team, number>();
  for (const execution of executions) {
    const team = teamOfAgent.get(execution.agent_id) ?? "Otros";
    totals.set(team, (totals.get(team) ?? 0) + 1);
  }
  const order: Team[] = [...TEAMS, "Otros"];
  return order.flatMap((team) => (totals.has(team) ? [{ team, runs: totals.get(team)! }] : []));
}
