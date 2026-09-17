import { ApiError, api, type AgentExecution, type DetailedHealth, type Incident } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { ServiceMap, type ServiceMapNode } from "@/components/service-map";
import { IncidentCard } from "@/components/incident-card";
import { IncidentReportForm } from "@/components/incident-report-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

async function fetchHealth(): Promise<{ health: DetailedHealth; apiReachable: boolean }> {
  try {
    return { health: await api.getHealth(), apiReachable: true };
  } catch (err) {
    if (err instanceof ApiError) {
      try {
        return { health: JSON.parse(err.message) as DetailedHealth, apiReachable: true };
      } catch {
        // fall through to the generic error state below
      }
    }
    return { health: { database: "error", migration: null, supabase_configured: false }, apiReachable: false };
  }
}

export default async function StatusPage() {
  const [{ health, apiReachable }, executions, incidents] = await Promise.all([
    fetchHealth(),
    api.listAgentExecutions().catch(() => [] as AgentExecution[]),
    api.listIncidents().catch(() => [] as Incident[]),
  ]);
  const openIncidents = incidents.filter((i) => i.status === "OPEN");
  const resolvedIncidents = incidents.filter((i) => i.status === "RESOLVED");

  const serviceMapNodes: ServiceMapNode[] = [
    { id: "users", label: "Usuarios", status: "idle", note: "No hay telemetría de tráfico real todavía" },
    { id: "frontend", label: "Frontend", status: "active" },
    {
      id: "api",
      label: "API",
      status: apiReachable ? "active" : "error",
      note: apiReachable ? undefined : "No se pudo contactar al backend",
    },
    {
      id: "database",
      label: "Postgres",
      status: health.database === "ok" ? "active" : "error",
    },
    {
      id: "auth_storage",
      label: "Auth / Storage",
      status: health.supabase_configured ? "active" : "idle",
      note: health.supabase_configured ? undefined : "Supabase no configurado",
    },
    { id: "queue", label: "Queue", status: "idle", note: "Sin endpoint de monitorización de cola todavía" },
    { id: "workers", label: "Workers", status: "idle", note: "Sin telemetría de workers todavía" },
    {
      id: "integrations",
      label: "Integraciones externas",
      status: "idle",
      note: "Sin monitorización de integraciones todavía",
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="System status" description="Operational health — no business data here, see Audit for that." />

      <Card>
        <CardHeader>
          <CardTitle>Service Map</CardTitle>
        </CardHeader>
        <CardContent>
          <ServiceMap nodes={serviceMapNodes} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Incidentes</CardTitle>
          {openIncidents.length > 0 ? <StatusChip status="OPEN" /> : null}
        </CardHeader>
        <CardContent className="space-y-4">
          <IncidentReportForm />

          {openIncidents.length > 0 ? (
            <div className="space-y-3">
              <p className="text-xs font-medium text-muted-foreground">Abiertos</p>
              {openIncidents.map((incident) => (
                <IncidentCard key={incident.id} incident={incident} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Sin incidentes abiertos.</p>
          )}

          {resolvedIncidents.length > 0 ? (
            <div className="space-y-3">
              <p className="text-xs font-medium text-muted-foreground">Resueltos</p>
              {resolvedIncidents.map((incident) => (
                <IncidentCard key={incident.id} incident={incident} />
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

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
