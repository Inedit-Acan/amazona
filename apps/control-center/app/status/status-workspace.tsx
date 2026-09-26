"use client";

import { useMemo } from "react";
import { ArrowRight, Bell, Boxes, CircleAlert, Code2, Gauge, ListChecks, ShieldCheck } from "lucide-react";
import type { Agent, AgentExecution, Incident, Job, PipelineRun } from "@/lib/api";
import { teamOf } from "@/lib/agents";
import { demoExecutions } from "@/lib/demo/agents";
import { relativeTime } from "@/lib/dates";
import { formatDuration, formatInteger, formatPercent } from "@/lib/format";
import { overallStatus, realSignals, workerSignal, type HealthSignal } from "@/lib/status";
import {
  costLines,
  cronRows,
  deploymentRows,
  healthScores,
  hourlySeries,
  incidentsView,
  integrationRows,
  migrationView,
  overallHealth,
  runtimeView,
  serviceRows,
  serviceSummary,
  statusKpis,
} from "@/lib/status-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { VerdictBanner } from "@/components/verdict-banner";
import { Button } from "@/components/ui/button";
import { STATUS_DESCRIPTION, STATUS_TITLE } from "./copy";
import {
  AgentRuntimeCard,
  CostCard,
  CronCard,
  DatabaseCard,
  DeploymentsCard,
  IncidentsCard,
  IntegrationsCard,
  JobRuntimeCard,
  MetricsCard,
  PipelineRunsCard,
  MigrationsCard,
  ServiceMapCard,
  ServicesCard,
  SystemHealthCard,
} from "./status-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: el backend solo responde una comprobación de salud (base de datos, migración y configuración de Supabase), el registro de agentes, su log de ejecuciones y los incidentes registrados a mano. Son de demostración el uptime y la latencia p95 de los 18 servicios, el estado de los doce sin telemetría, las series de las últimas 24 horas, las colas, las tareas programadas, las integraciones externas, las métricas del motor de base de datos, los despliegues y el coste de infraestructura. Real: que el frontend se ha renderizado, que la API responde y cuánto tarda, si la base de datos se puede consultar, la migración aplicada, si Supabase está configurado, los agentes registrados, sus ejecuciones fallidas de hoy y los incidentes.";

export function StatusWorkspace({
  signal,
  migration,
  agents,
  executions,
  incidents,
  jobs,
  pipelineRuns,
  now,
}: {
  signal: HealthSignal;
  migration: string | null;
  agents: Agent[];
  /** null = la petición falló: no es lo mismo que «cero ejecuciones». */
  executions: AgentExecution[] | null;
  incidents: Incident[] | null;
  jobs: Job[] | null;
  /** null = la petición falló. Igual que la cola, no se rellena con demo. */
  pipelineRuns: PipelineRun[] | null;
  now: number;
}) {
  // Mismo criterio que la pantalla de Agentes: si el log está vacío se usan las
  // ejecuciones de demostración, para que las dos pantallas cuenten lo mismo.
  const runs = useMemo(
    () => (executions && executions.length > 0 ? executions : demoExecutions(agents, teamOf, now, 1)),
    [agents, executions, now],
  );
  const workers = useMemo(() => workerSignal(runs), [runs]);
  const real = useMemo(() => realSignals(signal, workers), [signal, workers]);
  const rows = useMemo(() => serviceRows(signal, workers), [signal, workers]);
  const summary = useMemo(() => serviceSummary(rows), [rows]);
  const runtime = useMemo(() => runtimeView(agents, runs, now), [agents, runs, now]);
  const incidentsData = useMemo(() => incidentsView(incidents, now), [incidents, now]);
  const kpis = useMemo(() => statusKpis(rows, runtime, incidentsData, now), [rows, runtime, incidentsData, now]);
  const scores = useMemo(() => healthScores(signal, workers), [signal, workers]);
  const overall = overallStatus({ signal, openIncidents: incidentsData.open ?? 0 });
  const costs = useMemo(() => costLines(agents, runs, now), [agents, runs, now]);
  const usingDemoRuns = !executions || executions.length === 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title={STATUS_TITLE}
        description={STATUS_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <Button variant="outline" disabled title="Pendiente: todavía no hay página de estado pública.">
              Ver status público <ArrowRight />
            </Button>
          </>
        }
      />

      {/* Solo cuando algo va mal de verdad: en el mockup no hay banda, pero una
          caída real tiene que verse antes que nada. */}
      {overall.tone === "ok" ? null : <VerdictBanner tone={overall.tone} title={overall.title} detail={overall.detail} />}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7" aria-label="Indicadores de infraestructura">
        <KpiCard
          label="Disponibilidad (30 días)"
          value={formatPercent(kpis.uptime, 2)}
          icon={ShieldCheck}
          accent
          caption={`+${formatPercent(kpis.uptimeDelta, 2)} sobre el periodo anterior`}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="El backend no guarda historial de disponibilidad: es la media de los 18 servicios de demostración."
        />
        <KpiCard
          label="Latencia API p95"
          value={formatDuration(kpis.p95Ms)}
          icon={Gauge}
          caption={`${formatPercent(kpis.p95Delta, 0)} · medida real ahora: ${signal.latencyMs === null ? "—" : formatDuration(signal.latencyMs)}`}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="El p95 es de demostración. Lo único medido es el tiempo de la comprobación de salud de esta carga, que se enseña al lado."
        />
        <KpiCard
          label="Errores 5xx"
          value={formatPercent(kpis.errorRate, 2)}
          icon={CircleAlert}
          caption={`${formatPercent(kpis.errorRateDelta, 0)} sobre el periodo anterior`}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="El backend no publica contadores de respuestas por código."
        />
        <KpiCard
          label="Servicios operativos"
          value={`${kpis.servicesOperational} / ${kpis.servicesTotal}`}
          icon={Boxes}
          caption={`${summary.withRealSignal} con estado medido de verdad`}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="Seis servicios tienen estado real (frontend, API, Postgres, Auth, Storage y workers); los otros doce no tienen telemetría y su estado es de demostración."
        />
        <KpiCard
          label="Incidentes activos"
          value={kpis.openIncidents === null ? "—" : formatInteger(kpis.openIncidents)}
          icon={Bell}
          tone={kpis.openIncidents && kpis.openIncidents > 0 ? "warning" : "default"}
          caption={
            kpis.incidents30d === null
              ? "No se pudieron cargar"
              : `Últimos 30 días: ${kpis.incidents30d}${incidentsData.usingDemo ? " · lista de demostración" : ""}`
          }
          provenance={kpis.openIncidents === null ? "pending" : "verified"}
          provenanceCompact
          provenanceTooltip="Incidentes registrados a mano en el backend; el sistema no los abre solo."
        />
        <KpiCard
          label="Jobs en cola"
          value={formatInteger(kpis.queuedJobs)}
          icon={ListChecks}
          caption={`+${kpis.queuedDelta} respecto a la hora anterior`}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="No hay cola de trabajos expuesta: la profundidad de cada cola es de demostración."
        />
        <KpiCard
          label="Deploy actual"
          value={kpis.deployVersion}
          icon={Code2}
          caption={relativeTime(kpis.deployAt, now)}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="El backend no registra despliegues."
        />
      </section>

      <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-12" aria-label="Servicios y salud del sistema">
        <div className="min-w-0 2xl:col-span-4">
          <ServicesCard rows={rows} summary={summary} />
        </div>
        <div className="min-w-0 2xl:col-span-4">
          <ServiceMapCard real={real} summary={summary} />
        </div>
        <div className="min-w-0 2xl:col-span-2">
          <SystemHealthCard scores={scores} overall={overallHealth(scores)} />
        </div>
        <div className="min-w-0 space-y-3 2xl:col-span-2">
          <AgentRuntimeCard runtime={runtime} />
          <JobRuntimeCard jobs={jobs} now={now} />
          <PipelineRunsCard runs={pipelineRuns} />
        </div>
      </section>

      <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-12" aria-label="Métricas, integraciones y base de datos">
        <div className="min-w-0 2xl:col-span-5">
          <MetricsCard latency={hourlySeries("latency", now)} requests={hourlySeries("requests", now)} errors={hourlySeries("errors", now)} />
        </div>
        <div className="min-w-0 2xl:col-span-3">
          <IntegrationsCard rows={integrationRows()} />
        </div>
        <div className="min-w-0 2xl:col-span-2">
          <CronCard rows={cronRows(now)} now={now} />
        </div>
        <div className="min-w-0 2xl:col-span-2">
          <DatabaseCard state={real.postgres.state} />
        </div>
      </section>

      <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4" aria-label="Despliegues, migraciones, incidentes y coste">
        <DeploymentsCard rows={deploymentRows(now)} now={now} />
        <MigrationsCard view={migrationView(migration, now)} state={real.postgres.state} now={now} />
        <IncidentsCard
          rows={incidentsData.rows}
          open={incidentsData.open}
          reachable={incidentsData.reachable}
          usingDemo={incidentsData.usingDemo}
          now={now}
        />
        <CostCard lines={costs} />
      </section>

      <p className="text-[11px] text-muted-foreground">
        Esta pantalla mezcla una comprobación puntual hecha al cargarla con datos de demostración: no hay monitorización continua.
        {usingDemoRuns
          ? " El log de ejecuciones de agentes está vacío, así que los workers y el coste de inferencia usan las mismas ejecuciones de demostración que la pantalla de Agentes."
          : " Los workers y el coste de inferencia salen del log real de ejecuciones, igual que en la pantalla de Agentes."}
      </p>
    </div>
  );
}
