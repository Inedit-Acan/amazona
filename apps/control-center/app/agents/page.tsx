import { api, type Agent, type AgentExecution } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { AgentsWorkspace } from "./agents-workspace";

export default async function AgentsPage() {
  let agents: Agent[] = [];
  let executions: AgentExecution[] = [];
  let error: string | null = null;

  try {
    [agents, executions] = await Promise.all([api.listAgents(), api.listAgentExecutions()]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }

  return (
    <div>
      <PageHeader
        title="Agentes"
        description="Control y rendimiento de los agentes especialistas a los que el CEO enruta tareas, por capacidad. Los agentes son simulados y deterministas: el rendimiento sale de las ejecuciones registradas, sin evaluaciones ni costes medidos."
      />

      {error ? <ApiErrorAlert message={error} /> : <AgentsWorkspace agents={agents} executions={executions} />}
    </div>
  );
}
