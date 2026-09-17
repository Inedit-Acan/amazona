import { ApiError, api, type AgentExecution, type DetailedHealth } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

async function fetchHealth(): Promise<DetailedHealth> {
  try {
    return await api.getHealth();
  } catch (err) {
    if (err instanceof ApiError) {
      try {
        return JSON.parse(err.message) as DetailedHealth;
      } catch {
        // fall through to the generic error state below
      }
    }
    return { database: "error", migration: null, supabase_configured: false };
  }
}

export default async function StatusPage() {
  const [health, executions] = await Promise.all([
    fetchHealth(),
    api.listAgentExecutions().catch(() => [] as AgentExecution[]),
  ]);

  return (
    <div className="space-y-6">
      <PageHeader title="System status" description="Operational health — no business data here, see Audit for that." />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Database</CardTitle>
          </CardHeader>
          <CardContent>
            <StatusChip status={health.database === "ok" ? "AVAILABLE" : "FAILED"} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Migration</CardTitle>
          </CardHeader>
          <CardContent className="font-mono text-sm">{health.migration ?? "—"}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Supabase</CardTitle>
          </CardHeader>
          <CardContent>
            <StatusChip status={health.supabase_configured ? "AVAILABLE" : "DISABLED"} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent agent executions</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {executions.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No agent executions recorded yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Capability</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {executions.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(e.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.agent_id}</TableCell>
                    <TableCell className="text-sm">{e.capability}</TableCell>
                    <TableCell className="text-sm">{e.duration_ms.toFixed(1)} ms</TableCell>
                    <TableCell>
                      <StatusChip status={e.success ? "COMPLETED" : "FAILED"} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
