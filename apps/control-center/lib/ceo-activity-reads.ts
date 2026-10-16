import type { Agent, AgentExecution, AuditEntry } from "./api.ts";
import type { AuditQuery } from "./audit-query.ts";
import { activityBlock, ACTIVITY_LIMIT, type ActivityView } from "./ceo-activity.ts";
import { agentsContract, auditContract, executionsContract } from "./ceo-activity-contracts.ts";
import { areaExecutionsBlock, type AreaView } from "./ceo-area-executions.ts";
import { readList } from "./read-state.ts";

// LAS LECTURAS de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5): TRES peticiones, cada una UNA vez, en paralelo.
// Ninguna lleva ventana temporal: el selector 7 / 14 / 30 días gobierna solo Ingresos. La auditoría se pide UNA vez con
// `order=desc&limit=5` (micro-commit 5A del backend): las cinco más recientes, sin leer 500 filas ni pedir un total. Cada lectura se
// clasifica (`loaded` / `empty` / `error`), cada fila se comprueba contra su contrato, y un fallo o un contrato roto es `error` del
// bloque que lo sufre: nunca una lista vacía ni datos de demostración, y nunca apaga al otro bloque. Que la respuesta de la
// auditoría cumpla lo pedido (≤ 5 filas, más reciente primero) lo comprueba la vista de Actividad.

/** Lo que hace falta del cliente de la API; así las pruebas leen con una fuente que cuenta sus llamadas. */
export interface ActivitySource {
  listAudit(query: AuditQuery): Promise<AuditEntry[]>;
  listAgents(): Promise<Agent[]>;
  listAgentExecutions(): Promise<AgentExecution[]>;
}

export interface ActivityViews {
  activity: ActivityView;
  areas: AreaView;
}

export async function readActivity(source: ActivitySource): Promise<ActivityViews> {
  const [audit, agents, executions] = await Promise.all([
    readList(() => source.listAudit({ order: "desc", limit: ACTIVITY_LIMIT }), "la auditoría"),
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
