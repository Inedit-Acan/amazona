import { api, type Agent } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default async function AgentsPage() {
  let agents: Agent[] = [];
  let error: string | null = null;

  try {
    agents = await api.listAgents();
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  return (
    <div>
      <PageHeader
        title="Agents"
        description="Specialist agents the CEO can route tasks to, by capability. Deterministic simulated fixtures in Milestone 1."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {agents.map((agent) => (
            <Card key={agent.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">{agent.name}</CardTitle>
                  <StatusChip status={agent.status} />
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="text-muted-foreground capitalize">{agent.role} agent</p>
                <div className="flex flex-wrap gap-1">
                  {agent.capabilities.map((c) => (
                    <Badge key={c} variant="secondary" className="font-mono text-xs">
                      {c}
                    </Badge>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Reliability: {(agent.reliability_score * 100).toFixed(0)}%
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
