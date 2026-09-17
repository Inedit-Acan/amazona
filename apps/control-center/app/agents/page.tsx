import { api, type Agent, type AgentExecution } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { AgentCard } from "@/components/agent-card";

export default async function AgentsPage() {
  let agents: Agent[] = [];
  let executions: AgentExecution[] = [];
  let error: string | null = null;

  try {
    [agents, executions] = await Promise.all([api.listAgents(), api.listAgentExecutions()]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const executionsByAgent = new Map<string, AgentExecution[]>();
  for (const execution of executions) {
    const list = executionsByAgent.get(execution.agent_id) ?? [];
    list.push(execution);
    executionsByAgent.set(execution.agent_id, list);
  }

  return (
    <div>
      <PageHeader
        title="Agentes"
        description="Agentes especialistas a los que el CEO puede enrutar tareas, por capacidad. Fixtures simulados deterministas."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} executions={executionsByAgent.get(agent.id) ?? []} />
          ))}
        </div>
      )}
    </div>
  );
}
