import type { Agent, AgentExecution, Decision } from "./api.ts";
import { listOf, type ReadState } from "./read-state.ts";
import type { Settled } from "./revenue-view.ts";

// El resultado de una misión que se acaba de ejecutar (M47, Commit 2). Antes, tras ejecutar, la página pedía en «mejor
// esfuerzo» la decisión, las ejecuciones y los agentes con `.catch(() => [])`: si cualquiera fallaba, el resumen enseñaba
// «Agentes ejecutados: 0» (un ERROR convertido en cero) y el nombre del agente caía en su id sin avisar. Aquí cada lectura
// trae su estado y el resumen dice lo que no pudo leer.

export const NOT_AVAILABLE = "No disponible";

/** La decisión de la última misión que ve el grafo. `unavailable` ≠ `none`: la misión se ejecutó y su decisión no se pudo leer. */
export type DecisionState = { kind: "none" } | { kind: "loaded"; decision: Decision } | { kind: "unavailable" };

export interface MissionExecutionRow {
  id: string;
  agent: string;
  capability: string;
  durationMs: number;
  success: boolean;
}

export type ExecutedAgents = { kind: "value"; count: number } | { kind: "unavailable"; text: string };

export interface MissionOutcome {
  /** Cuántas ejecuciones tuvo esta misión. Solo con el log leído; si no, «No disponible» (jamás 0). */
  executed: ExecutedAgents;
  /** Las ejecuciones de esta misión; vacío si el log no se pudo leer (`executedUnavailable`). */
  rows: MissionExecutionRow[];
  /** Los nombres de los agentes no se pudieron leer: las filas llevan su id. */
  agentNamesUnavailable: boolean;
  /** La decisión completa no se pudo leer (la misión se ejecutó igual). */
  decisionNote: string | null;
  decision: DecisionState;
}

export function missionOutcome(input: {
  correlationId: string;
  decision: Settled<Decision>;
  executions: ReadState<AgentExecution[]>;
  agents: ReadState<Agent[]>;
}): MissionOutcome {
  const runs = listOf(input.executions);
  const agents = listOf(input.agents);
  const names = new Map((agents ?? []).map((agent) => [agent.id, agent.name] as const));

  const own = runs === null ? [] : runs.filter((run) => run.correlation_id === input.correlationId);
  const rows = own.map((run) => ({
    id: run.id,
    agent: names.get(run.agent_id) ?? run.agent_id,
    capability: run.capability,
    durationMs: run.duration_ms,
    success: run.success,
  }));

  return {
    executed: runs === null ? { kind: "unavailable", text: NOT_AVAILABLE } : { kind: "value", count: own.length },
    rows,
    agentNamesUnavailable: agents === null,
    decisionNote: input.decision.ok ? null : "La misión se ejecutó, pero no se pudo leer su decisión completa.",
    decision: input.decision.ok ? { kind: "loaded", decision: input.decision.data } : { kind: "unavailable" },
  };
}
