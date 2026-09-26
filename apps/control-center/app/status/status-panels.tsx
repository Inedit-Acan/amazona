"use client";

import { useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Cloud,
  Database,
  Globe,
  Link2,
  Loader2,
  Lock,
  Mail,
  MinusCircle,
  Monitor,
  Plus,
  Server,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";
import type { Job, JobStatus, PipelineRun } from "@/lib/api";
import { jobCounts, jobRows, queueVerdict, workerSeen } from "@/lib/jobs-view";
import {
  RUN_STATUS_LABEL,
  STEP_LABEL,
  pipelineCounts,
  pipelineRunRows,
  pipelineVerdict,
} from "@/lib/pipeline-view";
import {
  DEMO_DB_METRICS,
  DEMO_CRON_FAILURES_24H,
  HEALTH_NOTE,
} from "@/lib/demo/status";
import type {
  CostLine,
  CronRow,
  DeploymentRow,
  HealthScore,
  HourlyPoint,
  IncidentRow,
  IntegrationRow,
  MigrationView,
  RuntimeView,
  ServiceRow,
  ServiceSummary,
} from "@/lib/status-view";
import { costTotal } from "@/lib/status-view";
import type { RealSignal, ServiceState } from "@/lib/status";
import { relativeTime } from "@/lib/dates";
import { formatDuration, formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { ColumnChart } from "@/components/column-chart";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { IncidentReportForm } from "@/components/incident-report-form";
import { LineChart } from "@/components/line-chart";
import { ScoreGauge } from "@/components/score-gauge";
import { ServiceMap, type ServiceMapTier } from "@/components/service-map";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const STATE_LABEL: Record<ServiceState, string> = { operational: "Operativo", down: "Caído", no_signal: "Sin señal" };

/** Estado con icono y texto: nunca depende solo del color (spec §9.4). */
export function ServiceStateBadge({ state, className }: { state: ServiceState; className?: string }) {
  const Icon = state === "operational" ? CheckCircle2 : state === "down" ? XCircle : MinusCircle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap",
        state === "operational" && "text-primary",
        state === "down" && "text-destructive",
        state === "no_signal" && "text-muted-foreground",
        className,
      )}
    >
      <Icon className="size-3.5 shrink-0" /> {STATE_LABEL[state]}
    </span>
  );
}

/** Barra fina de porcentaje (uso de CPU, workers ocupados, System Health…). */
function Meter({ value, tone = "primary", className }: { value: number; tone?: "primary" | "warning"; className?: string }) {
  return (
    <div className={cn("h-1.5 min-w-8 flex-1 overflow-hidden rounded-full bg-muted", className)}>
      <div
        className={cn("h-full rounded-full", tone === "warning" ? "bg-warning" : "bg-primary")}
        style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }}
      />
    </div>
  );
}

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}h`;
}

// --- Servicios ----------------------------------------------------------------------

export function ServicesCard({ rows, summary }: { rows: ServiceRow[]; summary: ServiceSummary }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Servicios</CardTitle>
        <CardAction>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary">
            <span className="size-1.5 rounded-full bg-primary" aria-hidden />
            {summary.operational} / {summary.total} operativos
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="overflow-x-auto">
          <Table className="text-[11px] [&_td]:px-1 [&_td]:py-1 [&_th]:h-8 [&_th]:px-1">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Servicio</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Uptime</TableHead>
                <TableHead className="w-11" aria-label="Tendencia" />
                <TableHead className="text-right">p95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} title={row.note}>
                  <TableCell className="font-medium">
                    <span className="flex items-center gap-1">
                      {row.name}
                      {row.isDemo ? null : (
                        <ShieldCheck className="size-3 shrink-0 text-primary/70" aria-label="Estado medido de verdad" />
                      )}
                    </span>
                  </TableCell>
                  <TableCell>
                    <ServiceStateBadge state={row.state} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatPercent(row.uptime, row.uptime === 1 ? 0 : 2)}</TableCell>
                  <TableCell>
                    {row.trend.length > 0 ? <Sparkline values={row.trend} width={40} height={16} /> : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {row.p95Ms === null ? "—" : formatDuration(row.p95Ms)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="text-[11px] text-muted-foreground">
          El estado está medido de verdad <ShieldCheck className="inline size-3 align-[-1px] text-primary/70" /> en{" "}
          {summary.withRealSignal} de {summary.total} servicios: frontend, API, Postgres, Auth, Storage y los workers de agentes.
          El uptime (30 días), la latencia p95 y la tendencia son de demostración en todos.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Mapa de servicios --------------------------------------------------------------

const DEMO_NODE_NOTE = "Sin telemetría: el estado es de demostración.";

export function ServiceMapCard({ real, summary }: { real: Record<string, RealSignal>; summary: ServiceSummary }) {
  const mapState = (signal: RealSignal) => (signal.state === "down" ? "error" : signal.state === "no_signal" ? "idle" : "active");
  const tiers: ServiceMapTier[] = [
    {
      nodes: [{ id: "users", label: "Usuarios", icon: Users, col: 5, span: 4, status: "idle", note: "No hay telemetría de tráfico real todavía." }],
    },
    {
      nodes: [{ id: "frontend", label: "Frontend", icon: Monitor, col: 5, span: 4, status: mapState(real.frontend), note: real.frontend.note }],
    },
    {
      nodes: [{ id: "gateway", label: "API Gateway", icon: Server, col: 5, span: 4, status: mapState(real.api), note: real.api.note }],
    },
    {
      hubId: "backend",
      nodes: [
        { id: "auth", label: "Auth", icon: Lock, col: 1, span: 3, status: mapState(real.auth), note: real.auth.note },
        { id: "backend", label: "Backend", icon: Boxes, col: 5, span: 4, status: mapState(real.api), note: real.api.note },
        { id: "storage", label: "Storage", icon: Database, col: 10, span: 3, status: mapState(real.storage), note: real.storage.note },
      ],
    },
    {
      nodes: [
        { id: "postgres", label: "Postgres", icon: Database, col: 2, span: 4, status: mapState(real.postgres), note: real.postgres.note },
        { id: "queue", label: "Queue", icon: Boxes, col: 8, span: 4, status: "demo", note: DEMO_NODE_NOTE },
      ],
    },
    {
      nodes: [{ id: "workers", label: "Workers (Agentes)", icon: Cloud, col: 4, span: 6, status: mapState(real.workers), note: real.workers.note }],
    },
    {
      nodes: [
        { id: "integrations", label: "Integraciones externas", icon: Cloud, col: 1, span: 3, status: "demo", note: DEMO_NODE_NOTE },
        { id: "email", label: "Email", icon: Mail, col: 4, span: 3, status: "demo", note: DEMO_NODE_NOTE },
        { id: "amazon", label: "Amazon SP-API", icon: Globe, col: 7, span: 3, status: "demo", note: DEMO_NODE_NOTE },
        { id: "other_apis", label: "Otras APIs", icon: Link2, col: 10, span: 3, status: "demo", note: DEMO_NODE_NOTE },
      ],
    },
  ];

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Mapa de servicios</CardTitle>
        <CardAction>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-primary">
            <span className="size-1.5 rounded-full bg-primary" aria-hidden />
            {summary.down > 0 ? `${summary.down} servicio${summary.down === 1 ? "" : "s"} caído${summary.down === 1 ? "" : "s"}` : "Todos los servicios operativos"}
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <ServiceMap tiers={tiers} />
        <p className="text-[11px] text-muted-foreground">
          Borde continuo: estado medido de verdad · borde a trazos: estado de demostración · gris: sin telemetría. Pasa el cursor por
          cada nodo para ver el motivo.
        </p>
      </CardContent>
    </Card>
  );
}

// --- System Health ------------------------------------------------------------------

export function SystemHealthCard({ scores, overall }: { scores: HealthScore[]; overall: number | null }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>System Health</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {overall === null ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Sin señal suficiente para puntuar la salud del sistema.</p>
        ) : (
          <ScoreGauge value={overall} label="Salud del sistema" />
        )}
        <ul className="space-y-1.5">
          {scores.map((score) => (
            <li key={score.key} className="flex items-center gap-2 text-xs">
              <span className={cn("w-20 shrink-0 truncate", score.isDemo ? "text-muted-foreground" : "text-foreground")}>{score.label}</span>
              <Meter value={(score.score ?? 0) / 100} className={score.isDemo ? "opacity-70" : undefined} />
              <span className="w-7 shrink-0 text-right tabular-nums">{score.score ?? "—"}</span>
            </li>
          ))}
        </ul>
        <p className="rounded-lg border border-dashed p-2.5 text-center text-[11px] text-muted-foreground">
          {HEALTH_NOTE}
        </p>
        <p className="text-[11px] text-muted-foreground">
          API, Database, Auth, Storage y Workers salen de la señal real; Queues, Integrations, Security y Observability son de
          demostración.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Agent Runtime ------------------------------------------------------------------

function RuntimeStat({ value, label, tone }: { value: string; label: string; tone?: "danger" }) {
  return (
    <div className="flex items-baseline gap-2.5">
      <span className={cn("shrink-0 text-xl leading-none font-semibold tabular-nums", tone === "danger" ? "text-destructive" : "text-foreground")}>
        {value}
      </span>
      <span className="min-w-0 text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export function AgentRuntimeCard({ runtime }: { runtime: RuntimeView }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Agent Runtime</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-2.5">
          <div className="space-y-1">
            <p className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
              <span className="min-w-0 truncate">Workers activos</span>
              <span className="shrink-0 tabular-nums">
                <span className="text-base font-semibold text-foreground">{runtime.workersActive}</span> de {runtime.workersTotal}
              </span>
            </p>
            <Meter value={runtime.workersActive / runtime.workersTotal} />
          </div>
          <div className="space-y-1">
            <p className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
              <span className="min-w-0 truncate">Workers ocupados</span>
              <span className="shrink-0 tabular-nums">
                <span className="text-base font-semibold text-foreground">{runtime.workersBusy}</span> de {runtime.workersActive}
              </span>
            </p>
            <div className="flex items-center gap-2">
              <Meter value={runtime.busyRatio} />
              <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatPercent(runtime.busyRatio, 0)}</span>
            </div>
          </div>
        </div>

        <div className="space-y-2 border-t pt-3">
          <RuntimeStat value={formatInteger(runtime.runningJobs)} label="Jobs ejecutándose" />
          <RuntimeStat value={formatInteger(runtime.pendingJobs)} label="Jobs pendientes" />
          <RuntimeStat value={formatInteger(runtime.failedJobs)} label="Jobs fallidos hoy (real)" tone={runtime.failedJobs > 0 ? "danger" : undefined} />
          <RuntimeStat value={`${runtime.avgQueueSeconds.toLocaleString("es-ES", { minimumFractionDigits: 1 })} s`} label="Tiempo medio en cola" />
        </div>

        <div className="space-y-1.5 border-t pt-3">
          <p className="text-sm font-medium">Queues</p>
          <ul className="space-y-1">
            {runtime.queues.map((queue) => (
              <li key={queue.id} className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate font-mono text-muted-foreground">{queue.id}</span>
                <span className="shrink-0 tabular-nums">{queue.depth}</span>
              </li>
            ))}
            <li className="flex items-center justify-between gap-2 text-xs">
              <span className="flex min-w-0 items-center gap-1.5 truncate">
                <AlertTriangle className="size-3.5 shrink-0 text-warning" />
                Dead-letter queue
              </span>
              <span className="shrink-0 tabular-nums text-destructive">{runtime.deadLetter}</span>
            </li>
          </ul>
          <p className="pt-1 text-[11px] text-muted-foreground">Tarea más antigua: {runtime.oldestTaskSeconds} s</p>
          <p className="text-[11px] text-muted-foreground">
            Real: los agentes registrados y las ejecuciones fallidas de hoy. De demostración: los jobs en ejecución, las colas, el
            tiempo medio en cola y la dead-letter queue.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Métricas principales -----------------------------------------------------------

function MiniChartFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border bg-background/40 p-2.5">
      <p className="mb-1 text-xs font-medium">{title}</p>
      {children}
    </div>
  );
}

export function MetricsCard({
  latency,
  requests,
  errors,
}: {
  latency: HourlyPoint[];
  requests: HourlyPoint[];
  errors: HourlyPoint[];
}) {
  const hourOf = (points: HourlyPoint[], x: number) => points.find((point) => point.x === x)?.hour ?? 0;
  // Una etiqueta cada seis horas, como en el mockup.
  const ticks = [0, 6, 12, 18, 23];

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Métricas principales</CardTitle>
        <CardAction>
          <span className="rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground">Últimas 24 horas</span>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="grid gap-2.5 sm:grid-cols-3">
          <MiniChartFrame title="Latencia API (p95)">
            <LineChart
              series={[{ key: "latency", label: "p95", color: "var(--emerald)", points: latency.map((p) => ({ x: p.x, y: p.value })) }]}
              ariaLabel="Latencia p95 de la API en las últimas 24 horas"
              formatY={(value) => `${Math.round(value)}`}
              formatX={(x) => formatHour(hourOf(latency, x))}
              hoverTitle={(x) => formatHour(hourOf(latency, x))}
              xTicks={ticks}
              yLabel="ms"
              legend={false}
              dots={false}
              compact
              height={120}
            />
          </MiniChartFrame>
          <MiniChartFrame title="Requests por minuto">
            <ColumnChart
              data={requests.map((p) => ({ x: p.x, value: p.value }))}
              ariaLabel="Requests por minuto en las últimas 24 horas"
              formatY={(value) => (value >= 1000 ? `${value / 1000}K` : String(value))}
              formatX={(x) => formatHour(hourOf(requests, x))}
              xTicks={ticks}
              height={120}
            />
          </MiniChartFrame>
          <MiniChartFrame title="Tasa de errores">
            <LineChart
              series={[{ key: "errors", label: "5xx", color: "var(--danger)", points: errors.map((p) => ({ x: p.x, y: p.value })) }]}
              ariaLabel="Tasa de errores en las últimas 24 horas"
              formatY={(value) => formatPercent(value, value === 0 ? 0 : 1)}
              formatX={(x) => formatHour(hourOf(errors, x))}
              hoverTitle={(x) => formatHour(hourOf(errors, x))}
              xTicks={ticks}
              legend={false}
              dots={false}
              compact
              height={120}
            />
          </MiniChartFrame>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Las tres series son de demostración: el backend no guarda historial de latencia, tráfico ni errores. Lo único medido de
          verdad es la latencia de la comprobación de salud de esta carga.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Integraciones externas ---------------------------------------------------------

export function IntegrationsCard({ rows }: { rows: IntegrationRow[] }) {
  const operational = rows.filter((row) => row.state === "operational").length;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Integraciones externas</CardTitle>
        <CardAction>
          <span className="text-xs text-muted-foreground">
            {operational} / {rows.length} operativas
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li key={row.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate">{row.name}</span>
              <ServiceStateBadge state={row.state} />
              <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">{formatDuration(row.latencyMs)}</span>
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">
          Datos de demostración: AMAZONA todavía no llama a estas APIs ni mide su estado, su latencia ni su consumo de límites.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Tareas programadas (Cron) ------------------------------------------------------

export function CronCard({ rows, now }: { rows: CronRow[]; now: number }) {
  const running = rows.filter((row) => row.running).length;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Tareas programadas (Cron)</CardTitle>
        <CardDescription className="text-xs">{running > 0 ? `${running} ejecutándose ahora` : "Todas al día"}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li key={row.id} className="flex items-start gap-1.5 text-xs">
              {row.running ? (
                <Loader2 className="mt-0.5 size-3.5 shrink-0 text-primary" />
              ) : (
                <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-primary" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate" title={row.name}>
                  {row.name}
                </span>
                <span className="block text-[11px] text-muted-foreground">
                  {row.cadence} ·{" "}
                  {row.running ? (
                    <span className="text-primary">Ejecutando</span>
                  ) : (
                    <span className="tabular-nums">
                      {new Date(row.lastRunAt!).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}
                    </span>
                  )}
                </span>
              </span>
            </li>
          ))}
        </ul>
        <div className="flex items-center justify-between gap-2 border-t pt-2 text-xs">
          <span className="text-muted-foreground">Fallidos últimas 24 h</span>
          <span className="tabular-nums">{DEMO_CRON_FAILURES_24H}</span>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Datos de demostración: el backend no expone ningún planificador. Las horas son UTC y se calculan sobre el momento de esta
          carga ({new Date(now).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC).
        </p>
      </CardContent>
    </Card>
  );
}

// --- Base de datos (Supabase) -------------------------------------------------------

function DbRow({ label, value, meter }: { label: string; value: string; meter?: number }) {
  return (
    <li className="flex items-center justify-between gap-2 text-xs">
      <span className="min-w-0 shrink-0 text-muted-foreground">{label}</span>
      <span className="flex min-w-0 flex-1 items-center justify-end gap-2">
        <span className="shrink-0 tabular-nums">{value}</span>
        {meter === undefined ? null : <Meter value={meter} className="max-w-20" />}
      </span>
    </li>
  );
}

export function DatabaseCard({ state }: { state: ServiceState }) {
  const metrics = DEMO_DB_METRICS;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Base de datos (Supabase)</CardTitle>
        <CardAction>
          <ServiceStateBadge state={state} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <ul className="space-y-1.5">
          <DbRow label="CPU" value={formatPercent(metrics.cpu, 0)} meter={metrics.cpu} />
          <DbRow label="Memoria" value={formatPercent(metrics.memory, 0)} meter={metrics.memory} />
          <DbRow label="Conexiones" value={`${metrics.connections} / ${metrics.maxConnections}`} meter={metrics.connections / metrics.maxConnections} />
          <DbRow label="Cache hit" value={formatPercent(metrics.cacheHit)} meter={metrics.cacheHit} />
          <DbRow label="Queries lentas" value={formatInteger(metrics.slowQueries)} meter={0.05} />
          <DbRow label="Locks" value={formatInteger(metrics.locks)} meter={0} />
          <DbRow label="Storage" value={formatPercent(metrics.storage, 0)} meter={metrics.storage} />
          <DbRow label="IOPS" value={metrics.iops} />
        </ul>
        <p className="text-[11px] text-muted-foreground">
          Real: que el backend puede consultar la base de datos. Las métricas del motor (CPU, memoria, conexiones, cache, queries,
          locks, storage e IOPS) son de demostración.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Deployments --------------------------------------------------------------------

export function DeploymentsCard({ rows, now }: { rows: DeploymentRow[]; now: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Deployments</CardTitle>
        <CardAction>
          <Button size="sm" variant="outline" disabled title="Pendiente: el backend no expone el historial de despliegues.">
            Ver todos <ArrowRight />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <ul className="space-y-2">
          {rows.map((row, index) => (
            <li key={row.version} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium tabular-nums">{row.version}</span>
                {index === 0 ? (
                  <span className="rounded-md border border-primary/30 bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                    {row.environment}
                  </span>
                ) : null}
                <span className="text-muted-foreground">{relativeTime(row.at, now)}</span>
                <span className="ml-auto inline-flex items-center gap-1 text-primary">
                  <CheckCircle2 className="size-3.5" /> Successful
                </span>
              </div>
              {index === 0 ? <p className="text-[11px] text-muted-foreground">• {row.notes.join(" • ")}</p> : null}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">Datos de demostración: no hay registro de despliegues en el backend.</p>
      </CardContent>
    </Card>
  );
}

// --- Migraciones --------------------------------------------------------------------

export function MigrationsCard({ view, state, now }: { view: MigrationView; state: ServiceState; now: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Migraciones de base de datos</CardTitle>
        <CardAction>
          <ServiceStateBadge state={state} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <dl className="space-y-1.5 text-xs">
          <div className="flex items-start justify-between gap-2">
            <dt className="shrink-0 text-muted-foreground">Versión actual</dt>
            <dd className="min-w-0 text-right font-mono break-all">{view.current}</dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="shrink-0 text-muted-foreground">Estado</dt>
            <dd className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                <CheckCircle2 className="size-3" /> Applied
              </span>
              <span className="text-muted-foreground">{relativeTime(view.appliedAt, now)}</span>
            </dd>
          </div>
          <div className="flex items-start justify-between gap-2">
            <dt className="shrink-0 text-muted-foreground">Versión anterior</dt>
            <dd className="min-w-0 text-right font-mono break-all text-muted-foreground">{view.previous}</dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Pendientes</dt>
            <dd className="tabular-nums">{view.pending}</dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="text-muted-foreground">Fallidas</dt>
            <dd className="tabular-nums">{view.failed}</dd>
          </div>
        </dl>
        <p className="text-[11px] text-muted-foreground">
          {view.currentIsReal
            ? "La versión actual la devuelve la comprobación de salud del backend."
            : "El backend no devuelve versión de esquema: la actual también es de demostración."}{" "}
          El momento de aplicación, la versión anterior y los contadores son de demostración.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Incidentes ---------------------------------------------------------------------

export function IncidentsCard({
  rows,
  open,
  reachable,
  usingDemo,
  now,
}: {
  rows: IncidentRow[];
  open: number | null;
  reachable: boolean;
  usingDemo: boolean;
  now: number;
}) {
  const [reporting, setReporting] = useState(false);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Incidentes</CardTitle>
        <CardAction>
          {open === null ? (
            <span className="text-xs text-muted-foreground">Sin respuesta</span>
          ) : open > 0 ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap text-warning">
              <AlertTriangle className="size-3.5" />
              {open} activo{open === 1 ? "" : "s"}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap text-primary">
              <CheckCircle2 className="size-3.5" /> Sin incidentes activos
            </span>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={() => setReporting((value) => !value)}>
            <Plus /> {reporting ? "Cancelar" : "Registrar incidente"}
          </Button>
        </div>
        {reporting ? <IncidentReportForm /> : null}
        {!reachable ? (
          <p className="text-xs text-muted-foreground">No se pudieron cargar los incidentes: el backend no responde.</p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              Últimos 30 días ({rows.length}){usingDemo ? " — de demostración" : ""}
            </p>
            <ul className="space-y-1.5">
              {rows.map((row) => (
                <li key={row.id} className="flex items-start gap-2 text-xs">
                  <span className="w-14 shrink-0 font-mono text-muted-foreground">{row.code}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={row.title}>
                      {row.title}
                    </span>
                    <span className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-muted-foreground">
                      {row.open ? (
                        <span className="inline-flex items-center gap-1 font-medium text-warning">
                          <AlertTriangle className="size-3" /> Abierto
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 font-medium text-primary">
                          <span className="size-1.5 rounded-full bg-primary" aria-hidden /> Resuelto
                        </span>
                      )}
                      <span aria-hidden>·</span>
                      <span className="tabular-nums">
                        {row.resolvedInMinutes === null ? relativeTime(row.at, now) : `${row.resolvedInMinutes} min`}
                      </span>
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        <p className="text-[11px] text-muted-foreground">
          {usingDemo
            ? "El backend no tiene ningún incidente registrado en los últimos 30 días: los de la lista son de demostración. Los incidentes se abren a mano («Registrar»), el sistema no los detecta solo."
            : "Incidentes reales del backend. Se abren a mano («Registrar»), el sistema no los detecta solo; causa e impacto siguen pendientes."}
        </p>
      </CardContent>
    </Card>
  );
}

// --- Coste de infraestructura -------------------------------------------------------

export function CostCard({ lines }: { lines: CostLine[] }) {
  const total = costTotal(lines);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Coste de infraestructura (hoy)</CardTitle>
        <CardAction>
          <span className="text-base font-semibold text-primary tabular-nums">{formatEuro(total)}</span>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <ul className="space-y-1.5">
          {lines.map((line) => (
            <li key={line.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex min-w-0 items-center gap-1.5 truncate">
                {line.label}
                {line.isEstimate ? (
                  <DataProvenanceBadge
                    status="estimated"
                    compact
                    tooltip="Ejecuciones reales de agentes de hoy por el coste por ejecución de demostración de cada equipo: el mismo número que el coste de hoy de la pantalla de Agentes."
                  />
                ) : null}
              </span>
              <span className="shrink-0 tabular-nums">{formatEuro(line.amount)}</span>
            </li>
          ))}
        </ul>
        <div className="flex justify-end">
          <Button size="sm" variant="outline" disabled title="Pendiente: el backend no desglosa el coste de infraestructura.">
            Ver detalle <ArrowRight />
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Base de datos, storage, functions y APIs externas son de demostración: no hay medición de consumo.
        </p>
      </CardContent>
    </Card>
  );
}


/** Nombre legible de cada estado de un paso del pipeline. */
const STEP_STATUS_LABEL: Record<string, string> = {
  PENDING: "pendiente",
  RUNNING: "en marcha",
  COMPLETED: "terminado",
  FAILED: "fallido",
  SKIPPED: "no ejecutado",
  CANCELLED: "cancelado",
};

/** Ejecuciones del pipeline (Milestone 32).
 *
 * Igual que la tarjeta del runtime de trabajos, sin datos de demostración: o el
 * backend responde las ejecuciones, o no se enseña nada. Una ejecución inventada
 * diría que el sistema está descubriendo productos cuando no lo está. */
export function PipelineRunsCard({ runs }: { runs: PipelineRun[] | null }) {
  if (runs === null) {
    return (
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Pipeline</CardTitle>
          <CardDescription className="text-xs">Sin respuesta del backend</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No se pudieron leer las ejecuciones. No se enseña una estimación: una ejecución inventada diría
            que el sistema está descubriendo productos cuando no lo está.
          </p>
        </CardContent>
      </Card>
    );
  }

  const counts = pipelineCounts(runs);
  const verdict = pipelineVerdict(counts);
  const rows = pipelineRunRows(runs);
  const tone =
    verdict.tone === "error" ? "text-destructive" : verdict.tone === "warning" ? "text-warning" : "text-primary";

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Pipeline
          <DataProvenanceBadge
            status="verified"
            compact
            tooltip="Ejecuciones reales del backend: sin datos de demostración."
          />
        </CardTitle>
        <CardDescription className={`text-xs ${tone}`}>{verdict.headline}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-muted-foreground">{verdict.detail}</p>

        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "En curso", value: counts.queued + counts.running },
            { label: "Completadas", value: counts.completed },
            { label: "Incompletas", value: counts.partial },
            { label: "Paradas", value: counts.failed + counts.blocked + counts.cancelled },
          ].map((cell) => (
            <div key={cell.label} className="rounded-md border p-2">
              <p className="text-[10px] text-muted-foreground">{cell.label}</p>
              <p className="text-base font-semibold tabular-nums">{formatInteger(cell.value)}</p>
            </div>
          ))}
        </div>

        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">Todavía no se ha encolado ninguna ejecución.</p>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((row) => (
              <li key={row.correlationId} className="flex items-start justify-between gap-2 text-xs">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {row.category} · {row.market.toUpperCase()}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">
                    {RUN_STATUS_LABEL[row.status]} · {row.progress.completed}/{row.progress.total} pasos
                    {row.progress.current
                      ? ` · ${STEP_LABEL[row.progress.current] ?? row.progress.current} ${
                          STEP_STATUS_LABEL[row.progress.currentStatus ?? ""] ?? ""
                        }`
                      : ""}
                  </span>
                  {row.error ? (
                    <span className="block truncate text-[11px] text-destructive" title={row.error}>
                      {row.error}
                    </span>
                  ) : null}
                </span>
                {row.needsReview ? (
                  <span className="shrink-0 text-[10px] text-warning">revisión</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}


/** Nombre legible de cada estado del runtime. */
const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  PENDING: "Programado",
  QUEUED: "En cola",
  RUNNING: "Ejecutando",
  RETRYING: "Reintentando",
  WAITING_APPROVAL: "Esperando aprobación",
  BLOCKED: "Bloqueado",
  COMPLETED: "Completado",
  FAILED: "Agotado",
  CANCELLED: "Cancelado",
};

/** Runtime de trabajos (Milestone 31).
 *
 * Es el único panel de esta pantalla sin datos de demostración: o el backend
 * responde la cola, o no se enseña nada. Una cola inventada diría que el sistema
 * está trabajando cuando no lo está. */
export function JobRuntimeCard({
  jobs,
  now,
}: {
  jobs: Job[] | null;
  now: number;
}) {
  if (jobs === null) {
    return (
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Runtime de trabajos</CardTitle>
          <CardDescription className="text-xs">Sin respuesta del backend</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">
            No se pudo leer la cola. No se enseña una estimación: una cola inventada diría que el sistema
            está trabajando cuando no lo está.
          </p>
        </CardContent>
      </Card>
    );
  }

  const counts = jobCounts(jobs);
  const verdict = queueVerdict(counts, workerSeen(jobs));
  const rows = jobRows(jobs);
  const tone =
    verdict.tone === "error" ? "text-destructive" : verdict.tone === "warning" ? "text-warning" : "text-primary";

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Runtime de trabajos
          <DataProvenanceBadge status="verified" compact tooltip="Cola real del backend: sin datos de demostración." />
        </CardTitle>
        <CardDescription className={`text-xs ${tone}`}>{verdict.headline}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[11px] text-muted-foreground">{verdict.detail}</p>

        <div className="grid grid-cols-2 gap-2">
          {[
            { label: "En cola", value: counts.queued + counts.pending },
            { label: "Ejecutando", value: counts.running },
            { label: "Reintentando", value: counts.retrying },
            { label: "Agotados", value: counts.failed },
          ].map((cell) => (
            <div key={cell.label} className="rounded-md border p-2">
              <p className="text-[10px] text-muted-foreground">{cell.label}</p>
              <p className="text-base font-semibold tabular-nums">{formatInteger(cell.value)}</p>
            </div>
          ))}
        </div>

        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">Todavía no se ha encolado ningún trabajo.</p>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((row) => (
              <li key={row.id} className="flex items-start justify-between gap-2 text-xs">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium" title={row.type}>
                    {row.type}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">
                    {JOB_STATUS_LABEL[row.status]} · intento {row.attempts} · {relativeTime(row.at, now)}
                  </span>
                  {row.error ? (
                    <span className="block truncate text-[11px] text-destructive" title={row.error}>
                      {row.error}
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
