import type { Agent, AgentExecution } from "@/lib/api";
import { StatusChip } from "@/components/status-chip";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** Success rate / latency / last activity are computed here from real
 * AgentExecutionLog rows — never a fabricated "coste"/"versión"/
 * "evaluación" figure, since no cost tracking, versioning, or eval
 * suite exists in the backend yet (parte2.md §6.5 lists those too, but
 * this card only shows what the system can actually measure). */
export function AgentCard({ agent, executions }: { agent: Agent; executions: AgentExecution[] }) {
  const runCount = executions.length;
  const successRate = runCount > 0 ? executions.filter((e) => e.success).length / runCount : null;
  const avgLatencyMs =
    runCount > 0 ? executions.reduce((sum, e) => sum + e.duration_ms, 0) / runCount : null;
  const lastActivity =
    runCount > 0
      ? new Date(Math.max(...executions.map((e) => new Date(e.created_at).getTime())))
      : null;

  return (
    <Card>
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

        <div className="grid grid-cols-2 gap-x-3 gap-y-2 border-t pt-3">
          <div>
            <p className="text-xs text-muted-foreground">Reliability</p>
            <div className="flex items-center gap-1.5">
              <p className="font-medium">{(agent.reliability_score * 100).toFixed(0)}%</p>
              <DataProvenanceBadge status="estimated" tooltip="Nominal reliability score set on the agent descriptor." />
            </div>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Éxito (ejecuciones reales)</p>
            {successRate !== null ? (
              <div className="flex items-center gap-1.5">
                <p className="font-medium">{(successRate * 100).toFixed(0)}%</p>
                <DataProvenanceBadge status="verified" tooltip={`${runCount} ejecuciones registradas`} />
              </div>
            ) : (
              <p className="text-muted-foreground">Sin ejecuciones</p>
            )}
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Latencia media</p>
            <p className="font-medium">{avgLatencyMs !== null ? `${avgLatencyMs.toFixed(0)}ms` : "—"}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Última actividad</p>
            <p className="font-medium">{lastActivity ? lastActivity.toLocaleString() : "—"}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
