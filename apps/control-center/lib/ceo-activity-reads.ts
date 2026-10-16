import type { Agent, AgentExecution, AuditEntry } from "./api.ts";
import { activityBlock, type ActivityView } from "./ceo-activity.ts";
import { agentsContract, auditContract, executionsContract } from "./ceo-activity-contracts.ts";
import { areaExecutionsBlock, type AreaView } from "./ceo-area-executions.ts";
import { readList } from "./read-state.ts";

// LAS LECTURAS de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5): TRES peticiones, cada una UNA vez, en paralelo.
// Ninguna lleva ventana temporal ni filtro: el selector 7 / 14 / 30 días gobierna solo Ingresos, y la auditoría se pide entera (sin
// `correlation_id`) porque la guarda de las 500 entradas necesita saber si la respuesta es el registro completo. Cada lectura se
// clasifica (`loaded` / `empty` / `error`), cada fila se comprueba contra su contrato, y un fallo o un contrato roto es `error` del
// bloque que lo sufre: nunca una lista vacía ni datos de demostración, y nunca apaga al otro bloque.

/** Lo que hace falta del cliente de la API; así las pruebas leen con una fuente que cuenta sus llamadas. */
export interface ActivitySource {
  listAudit(): Promise<AuditEntry[]>;
  listAgents(): Promise<Agent[]>;
  listAgentExecutions(): Promise<AgentExecution[]>;
}

export interface ActivityViews {
  activity: ActivityView;
  areas: AreaView;
}

export async function readActivity(source: ActivitySource): Promise<ActivityViews> {
  const [audit, agents, executions] = await Promise.all([
    readList(() => source.listAudit(), "la auditoría"),
    readList(() => source.listAgents(), "los agentes"),
    readList(() => source.listAgentExecutions(), "el log de ejecuciones"),
  ]);
  const registry = agentsContract(agents);
  return {
    activity: activityBlock({ audit: auditContract(audit), agents: registry }),
    areas: areaExecutionsBlock({ executions: executionsContract(executions), agents: registry }),
  };
}

export function readActivityNow(source: ActivitySource): Promise<ActivityViews> {
  return readActivity(source);
}
