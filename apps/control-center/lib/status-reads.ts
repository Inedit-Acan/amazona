import type { Agent, AgentExecution, ApiProviderUsage, Incident, Job, PipelineRun } from "./api.ts";
import { readList, type ReadState } from "./read-state.ts";

// LAS LECTURAS de /status (M47, Commit 6b). Antes eran seis `.catch(...)`: la lista de agentes caída era `[]` y el log de ejecuciones
// caído acababa mostrándose como ejecuciones de DEMOSTRACIÓN. Ahora cada lectura es un `ReadState`: un fallo es `error` (se dice, con
// nuestro texto) y nunca una lista vacía, un cero ni un dato de demostración.

export interface StatusSource {
  listAgentExecutions(): Promise<AgentExecution[]>;
  listIncidents(): Promise<Incident[]>;
  listAgents(): Promise<Agent[]>;
  listJobs(): Promise<Job[]>;
  listPipelineRuns(): Promise<PipelineRun[]>;
  listApiUsage(): Promise<ApiProviderUsage[]>;
}

export interface StatusPageReads {
  executions: ReadState<AgentExecution[]>;
  incidents: ReadState<Incident[]>;
  agents: ReadState<Agent[]>;
  jobs: ReadState<Job[]>;
  pipelineRuns: ReadState<PipelineRun[]>;
  apiUsage: ReadState<ApiProviderUsage[]>;
}

export async function readStatusPage(source: StatusSource): Promise<StatusPageReads> {
  const [executions, incidents, agents, jobs, pipelineRuns, apiUsage] = await Promise.all([
    readList(() => source.listAgentExecutions(), "el log de ejecuciones de agentes"),
    readList(() => source.listIncidents(), "los incidentes"),
    readList(() => source.listAgents(), "el registro de agentes"),
    readList(() => source.listJobs(), "la cola de trabajos"),
    readList(() => source.listPipelineRuns(), "las ejecuciones del pipeline"),
    readList(() => source.listApiUsage(), "el consumo de APIs externas"),
  ]);
  return { executions, incidents, agents, jobs, pipelineRuns, apiUsage };
}

/** Los avisos de las lecturas que fallaron o no se hicieron, uno por fuente, en el orden de la pantalla. */
export function statusFailures(reads: StatusPageReads): string[] {
  return [reads.agents, reads.executions, reads.jobs, reads.pipelineRuns, reads.incidents, reads.apiUsage].flatMap((state) =>
    state.kind === "error" ? [state.message] : state.kind === "unread" ? [state.reason] : [],
  );
}
