import type { Agent, AgentExecution } from "./api.ts";
import { readList, type ReadState } from "./read-state.ts";

// Las lecturas del grafo de agentes (M47, Commit 1). Antes eran dos `.catch(() => [])` dentro del componente: el error
// del backend se volvía una lista vacía y de una lista vacía salía el roster de demostración («13 Disponible»). Aquí cada
// lectura devuelve un `ReadState` y NINGUNA traga su error. Es una función pura sobre una fuente inyectable, para poder
// probar —con dobles que fallan de todas las formas— que un fallo no se convierte en un dato.

/** Lo que el grafo necesita del cliente de la API. `api` lo cumple; las pruebas pasan dobles. */
export interface NexusSource {
  listAgents(): Promise<Agent[]>;
  listAgentExecutions(): Promise<AgentExecution[]>;
}

export interface NexusReads {
  /** El registro de agentes. Sin una lectura válida no hay grafo. */
  agents: ReadState<Agent[]>;
  /** El log de ejecuciones. Sin él el grafo se dibuja igual, pero lo que depende de las ejecuciones no se enseña. */
  executions: ReadState<AgentExecution[]>;
}

export async function readNexus(source: NexusSource): Promise<NexusReads> {
  const [agents, executions] = await Promise.all([
    readList(() => source.listAgents(), "el registro de agentes"),
    readList(() => source.listAgentExecutions(), "el log de ejecuciones"),
  ]);
  return { agents, executions };
}
