import Link from "next/link";
import { Bot, ClipboardCheck, Compass, FolderKanban, Wallet } from "lucide-react";
import {
  api,
  type Agent,
  type AgentExecution,
  type Approval,
  type CFOReport,
  type EconomicsTimeseriesPoint,
  type Project,
} from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ApiErrorAlert } from "@/components/api-error";
import { StatusChip } from "@/components/status-chip";
import { KpiCard } from "@/components/kpi-card";
import { EmptyState } from "@/components/empty-state";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EconomicsActivityChart } from "@/components/economics-activity-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const FINANCIAL_HEALTH_LABEL: Record<CFOReport["financial_health_status"], string> = {
  HEALTHY: "Saludable",
  AT_RISK: "En riesgo",
  CRITICAL: "Crítico",
  NEEDS_REVIEW: "Requiere revisión",
};

export default async function DashboardPage() {
  let agents: Agent[] = [];
  let approvals: Approval[] = [];
  let projects: Project[] = [];
  let executions: AgentExecution[] = [];
  let cfoReports: CFOReport[] = [];
  let economicsTimeseries: EconomicsTimeseriesPoint[] = [];
  let error: string | null = null;

  try {
    [agents, approvals, projects, executions, cfoReports, economicsTimeseries] = await Promise.all([
      api.listAgents(),
      api.listApprovals(),
      api.listProjects(),
      api.listAgentExecutions(),
      api.listCFORuns(),
      api.getEconomicsTimeseries(30),
    ]);
  } catch (err) {
    error = err instanceof Error ? err.message : "Unknown error";
  }

  const pendingApprovals = approvals.filter((a) => a.status === "PENDING");
  const availableAgents = agents.filter((a) => a.status === "AVAILABLE");
  const latestCfoReport = cfoReports[0] ?? null;
  const agentsById = new Map(agents.map((a) => [a.id, a]));
  const recentExecutions = [...executions]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8);

  return (
    <div>
      <PageHeader
        title="Panel"
        description="Estado ejecutivo de AMAZONA — negocio simulado: sin dinero, pedidos, proveedores ni presentaciones fiscales reales."
      />

      {error ? (
        <ApiErrorAlert message={error} />
      ) : (
        <div className="space-y-6">
          <div className="flex items-center justify-end">
            <Button size="sm" nativeButton={false} render={<Link href="/ceo" />}>
              + Nuevo objetivo
            </Button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              label="Proyectos"
              value={projects.length}
              icon={FolderKanban}
              provenance="verified"
            />
            <KpiCard
              label="Agentes en línea"
              value={`${availableAgents.length}/${agents.length}`}
              icon={Bot}
              provenance="verified"
            />
            <KpiCard
              label="Aprobaciones pendientes"
              value={pendingApprovals.length}
              icon={ClipboardCheck}
              provenance="verified"
            />
            <KpiCard
              label="Salud financiera"
              value={latestCfoReport ? FINANCIAL_HEALTH_LABEL[latestCfoReport.financial_health_status] : "Sin datos"}
              icon={Wallet}
              caption={
                latestCfoReport?.data
                  ? `${latestCfoReport.data.total_products_analyzed} productos analizados`
                  : "Aún no se ha ejecutado el agente CFO"
              }
              provenance={latestCfoReport ? "estimated" : "pending"}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Actividad empresarial</CardTitle>
            </CardHeader>
            <CardContent>
              {recentExecutions.length === 0 ? (
                <EmptyState
                  icon={Bot}
                  title="Sin actividad de agentes todavía"
                  description="Las ejecuciones de agentes aparecerán aquí en cuanto se lance el primer objetivo o pipeline."
                />
              ) : (
                <ul className="divide-y">
                  {recentExecutions.map((execution) => {
                    const agent = agentsById.get(execution.agent_id);
                    return (
                      <li key={execution.id} className="flex items-center justify-between gap-4 py-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{agent?.name ?? execution.agent_id}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {execution.capability.replace(/_/g, " ")} ·{" "}
                            {new Date(execution.created_at).toLocaleString()}
                          </p>
                        </div>
                        <StatusChip status={execution.success ? "COMPLETED" : "FAILED"} />
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Decisiones necesarias</CardTitle>
            </CardHeader>
            <CardContent>
              {pendingApprovals.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nada esperando aprobación humana ahora mismo.</p>
              ) : (
                <ul className="divide-y">
                  {pendingApprovals.map((approval) => (
                    <li key={approval.id} className="flex items-center justify-between gap-4 py-3">
                      <div>
                        <p className="text-sm font-medium">{approval.action.replace(/_/g, " ")}</p>
                        <p className="text-xs text-muted-foreground">
                          Importe: {approval.amount != null ? `$${approval.amount.toFixed(2)}` : "n/a"} (simulado)
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <StatusChip status={approval.status} />
                        <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/approvals" />}>
                          Revisar
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Actividad económica — últimos 30 días</CardTitle>
              <DataProvenanceBadge
                status="verified"
                tooltip="Recuento y promedios reales de EconomicAnalysis, no ingresos ejecutados."
              />
            </CardHeader>
            <CardContent>
              <p className="mb-3 text-xs text-muted-foreground">
                Decisiones económicas analizadas por día — no es un ledger de ventas: AMAZONA sigue en fase de
                validación, ningún paso cobra dinero real todavía (ADR 0006).
              </p>
              <EconomicsActivityChart points={economicsTimeseries} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Oportunidades</CardTitle>
            </CardHeader>
            <CardContent>
              <EmptyState
                icon={Compass}
                title="Todavía no hay un radar agregado de oportunidades"
                description="Investigación analiza oportunidades por categoría bajo demanda — no existe hoy un feed agregado histórico de resultados. Lanza un análisis de mercado para ver candidatos."
                action={
                  <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                    Ir a Investigación
                  </Button>
                }
              />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
