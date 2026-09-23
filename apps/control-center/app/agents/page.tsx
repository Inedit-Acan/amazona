import { api, type Agent, type AgentExecution } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { AGENTS_DESCRIPTION, AGENTS_TITLE } from "./copy";
import { AgentsWorkspace } from "./agents-workspace";

export default async function AgentsPage() {
  let agents: Agent[] = [];
  let error: string | null = null;

  try {
    agents = await api.listAgents();
  } catch (err) {
    error = err instanceof Error ? err.message : "Error desconocido";
  }
  // El log de ejecuciones es opcional: sin él la pantalla sigue en pie.
  const executions: AgentExecution[] = await api.listAgentExecutions().catch(() => []);

  if (error) {
    return (
      <div>
        <PageHeader title={AGENTS_TITLE} description={AGENTS_DESCRIPTION} />
        <ApiErrorAlert message={error} />
      </div>
    );
  }

  // El instante se fija en el servidor: el coste del día y los «hace X» se
  // calculan con él y el cliente hidrata exactamente lo mismo.
  const now = new Date().getTime();

  return <AgentsWorkspace agents={agents} executions={executions} now={now} />;
}
