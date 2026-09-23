import type { Agent, AgentExecution, Incident } from "./api.ts";
import { teamOf } from "./agents.ts";
import { parseUtc } from "./dates.ts";
import { COST_PER_RUN } from "./demo/agents.ts";
import {
  DEMO_COST_LINES,
  DEMO_CRON,
  DEMO_DEAD_LETTER,
  DEMO_DEPLOYMENTS,
  DEMO_ERROR_RATE,
  DEMO_HEALTH_SCORES,
  DEMO_INCIDENTS,
  DEMO_INTEGRATIONS,
  DEMO_KPI_DELTAS,
  DEMO_LATENCY_BASE_MS,
  DEMO_MIGRATION_FALLBACK,
  DEMO_MIGRATIONS_FAILED,
  DEMO_MIGRATIONS_PENDING,
  DEMO_MIGRATION_HOURS_AGO,
  DEMO_OLDEST_TASK_SECONDS,
  DEMO_PREVIOUS_MIGRATION,
  DEMO_QUEUES,
  DEMO_QUEUE_WAIT_SECONDS,
  DEMO_REQUESTS_PER_MINUTE,
  DEMO_SERVICES,
  DEMO_WORKER_SLOTS,
  HOUR_MS,
  METRIC_HOURS,
  demoErrorFactor,
  demoHourFactor,
  demoQueueDepth,
  demoRunningJobs,
  demoTrend,
} from "./demo/status.ts";
import { realSignals, type HealthSignal, type ServiceState, type WorkerSignal } from "./status.ts";

// Vista de la pantalla de Estado e infraestructura (mockup docs/design/
// «estado de AMAZONA.png»). Real: la comprobación de salud (`/health/detailed`)
// y su latencia medida, el registro de agentes, el log de ejecuciones y los
// incidentes. Demo (lib/demo/status.ts): los doce servicios sin telemetría, el
// uptime y los percentiles, las series de 24 h, las colas, el cron, las
// integraciones, las métricas del motor de base de datos, los despliegues y los
// costes. Cada estructura dice qué parte es de demostración.

const DAY_MS = 86_400_000;
const round2 = (value: number) => Math.round(value * 100) / 100;

/** Hora en curso: las cifras de demostración que se mueven (colas, series) son
 * deterministas dentro de la misma hora, así que la pantalla no parpadea. */
export function hourKeyOf(at: number): string {
  return String(Math.floor(at / HOUR_MS));
}

// --- Servicios ----------------------------------------------------------------------

export interface ServiceRow {
  id: string;
  name: string;
  state: ServiceState;
  /** Disponibilidad de 30 días (siempre de demostración). */
  uptime: number;
  /** Latencia p95 (siempre de demostración); null cuando no aplica. */
  p95Ms: number | null;
  /** Latencia medida de verdad en esta carga (solo API y workers). */
  measuredMs: number | null;
  trend: number[];
  /** true cuando el estado del servicio es de demostración (no hay telemetría). */
  isDemo: boolean;
  note: string;
}

/** Los 18 servicios del mockup: los seis con señal real llevan su estado medido y
 * los otros doce el de demostración. Uptime y p95 son de demostración en todos. */
export function serviceRows(signal: HealthSignal, workers: WorkerSignal): ServiceRow[] {
  const real = realSignals(signal, workers);
  return DEMO_SERVICES.map((service) => {
    const own = real[service.id];
    return {
      id: service.id,
      name: service.name,
      state: own?.state ?? "operational",
      uptime: service.uptime,
      p95Ms: service.p95Ms,
      measuredMs: own?.measuredMs ?? null,
      trend: service.p95Ms === null ? [] : demoTrend(service.id, service.p95Ms),
      isDemo: own === undefined,
      note: own?.note ?? "Sin telemetría: el estado es de demostración.",
    };
  });
}

export interface ServiceSummary {
  operational: number;
  down: number;
  noSignal: number;
  total: number;
  /** Servicios cuyo estado sale de una señal real. */
  withRealSignal: number;
}

export function serviceSummary(rows: ServiceRow[]): ServiceSummary {
  return {
    operational: rows.filter((r) => r.state === "operational").length,
    down: rows.filter((r) => r.state === "down").length,
    noSignal: rows.filter((r) => r.state === "no_signal").length,
    total: rows.length,
    withRealSignal: rows.filter((r) => !r.isDemo).length,
  };
}

// --- KPIs de cabecera ---------------------------------------------------------------

export interface StatusKpis {
  /** Disponibilidad media de los 30 días (demo) y su variación. */
  uptime: number;
  uptimeDelta: number;
  /** p95 de la API (demo) y su variación relativa. */
  p95Ms: number;
  p95Delta: number;
  errorRate: number;
  errorRateDelta: number;
  servicesOperational: number;
  servicesTotal: number;
  /** Incidentes abiertos y de los últimos 30 días: null si el backend no respondió. */
  openIncidents: number | null;
  incidents30d: number | null;
  queuedJobs: number;
  queuedDelta: number;
  deployVersion: string;
  deployAt: number;
}

export function statusKpis(rows: ServiceRow[], runtime: RuntimeView, incidents: IncidentsView, now: number): StatusKpis {
  const summary = serviceSummary(rows);
  const uptime = rows.reduce((sum, row) => sum + row.uptime, 0) / rows.length;
  const deployment = DEMO_DEPLOYMENTS[0];
  return {
    uptime,
    uptimeDelta: DEMO_KPI_DELTAS.uptime,
    p95Ms: DEMO_SERVICES.find((s) => s.id === "api")?.p95Ms ?? DEMO_LATENCY_BASE_MS,
    p95Delta: DEMO_KPI_DELTAS.p95,
    errorRate: DEMO_ERROR_RATE,
    errorRateDelta: DEMO_KPI_DELTAS.errorRate,
    servicesOperational: summary.operational,
    servicesTotal: summary.total,
    openIncidents: incidents.open,
    incidents30d: incidents.total30d,
    queuedJobs: runtime.pendingJobs,
    queuedDelta: DEMO_KPI_DELTAS.queued,
    deployVersion: deployment.version,
    deployAt: now - deployment.hoursAgo * HOUR_MS,
  };
}

// --- System Health ------------------------------------------------------------------

export interface HealthScore {
  key: string;
  label: string;
  /** 0–100; null cuando no hay ni señal real ni valor de demostración. */
  score: number | null;
  isDemo: boolean;
}

const STATE_SCORE: Record<ServiceState, number | null> = { operational: 100, down: 0, no_signal: null };

/** Las cinco primeras puntuaciones salen de la señal real (la de workers, de la
 * tasa de éxito de las ejecuciones); las cuatro últimas son de demostración. */
export function healthScores(signal: HealthSignal, workers: WorkerSignal): HealthScore[] {
  const real = realSignals(signal, workers);
  const workersScore =
    workers.runs > 0 ? Math.round(((workers.runs - workers.failures) / workers.runs) * 100) : STATE_SCORE[real.workers.state];
  return [
    { key: "api", label: "API", score: STATE_SCORE[real.api.state], isDemo: false },
    { key: "database", label: "Database", score: STATE_SCORE[real.postgres.state], isDemo: false },
    { key: "auth", label: "Auth", score: STATE_SCORE[real.auth.state], isDemo: false },
    { key: "storage", label: "Storage", score: STATE_SCORE[real.storage.state], isDemo: false },
    { key: "workers", label: "Workers", score: workersScore, isDemo: false },
    { key: "queues", label: "Queues", score: DEMO_HEALTH_SCORES.queues, isDemo: true },
    { key: "integrations", label: "Integrations", score: DEMO_HEALTH_SCORES.integrations, isDemo: true },
    { key: "security", label: "Security", score: DEMO_HEALTH_SCORES.security, isDemo: true },
    { key: "observability", label: "Observability", score: DEMO_HEALTH_SCORES.observability, isDemo: true },
  ];
}

/** Media de las puntuaciones medibles; null si no hay ninguna. */
export function overallHealth(scores: HealthScore[]): number | null {
  const known = scores.flatMap((s) => (s.score === null ? [] : [s.score]));
  return known.length === 0 ? null : Math.round(known.reduce((sum, v) => sum + v, 0) / known.length);
}

// --- Agent Runtime ------------------------------------------------------------------

export interface RuntimeView {
  /** Agentes registrados y cuántos no están fuera de servicio (real). */
  workersActive: number;
  workersTotal: number;
  /** Agentes ocupados ahora mismo (real). */
  workersBusy: number;
  busyRatio: number;
  /** Trabajos en ejecución (demo) y pendientes (suma de las colas, demo). */
  runningJobs: number;
  pendingJobs: number;
  /** Ejecuciones fallidas hoy (real). */
  failedJobs: number;
  avgQueueSeconds: number;
  oldestTaskSeconds: number;
  queues: { id: string; depth: number }[];
  deadLetter: number;
}

export function runtimeView(agents: Agent[], executions: AgentExecution[], now: number): RuntimeView {
  const hourKey = hourKeyOf(now);
  const dayStart = now - (now % DAY_MS);
  const queues = DEMO_QUEUES.map((queue) => ({ id: queue.id, depth: demoQueueDepth(queue.id, hourKey) }));
  const slots = Math.max(DEMO_WORKER_SLOTS, agents.length);
  const active = agents.filter((agent) => agent.status !== "OFFLINE").length;
  const busy = agents.filter((agent) => agent.status === "BUSY").length;
  return {
    workersActive: active,
    workersTotal: slots,
    workersBusy: busy,
    busyRatio: active > 0 ? busy / active : 0,
    runningJobs: demoRunningJobs(hourKey),
    pendingJobs: queues.reduce((sum, queue) => sum + queue.depth, 0),
    failedJobs: executions.filter((e) => !e.success && parseUtc(e.created_at) >= dayStart).length,
    avgQueueSeconds: DEMO_QUEUE_WAIT_SECONDS,
    oldestTaskSeconds: DEMO_OLDEST_TASK_SECONDS,
    queues,
    deadLetter: DEMO_DEAD_LETTER,
  };
}

// --- Métricas principales (últimas 24 h) --------------------------------------------

export type MetricKey = "latency" | "requests" | "errors";

export interface HourlyPoint {
  /** 0 = hace 23 horas, 23 = la hora en curso. */
  x: number;
  /** Hora del día (UTC) del punto, para etiquetar el eje. */
  hour: number;
  value: number;
}

/** Serie horaria de demostración de las últimas 24 horas. */
export function hourlySeries(metric: MetricKey, now: number): HourlyPoint[] {
  const currentHour = Math.floor(now / HOUR_MS);
  return Array.from({ length: METRIC_HOURS }, (_, x) => {
    const slot = currentHour - (METRIC_HOURS - 1 - x);
    const key = String(slot);
    const value =
      metric === "latency"
        ? Math.round(DEMO_LATENCY_BASE_MS * demoHourFactor("latency", key))
        : metric === "requests"
          ? Math.round(DEMO_REQUESTS_PER_MINUTE * demoHourFactor("requests", key))
          : Math.round(DEMO_ERROR_RATE * demoErrorFactor(key) * 1e5) / 1e5;
    return { x, hour: new Date(slot * HOUR_MS).getUTCHours(), value };
  });
}

// --- Integraciones externas ---------------------------------------------------------

export interface IntegrationRow {
  id: string;
  name: string;
  state: ServiceState;
  latencyMs: number;
}

export function integrationRows(): IntegrationRow[] {
  return DEMO_INTEGRATIONS.map((integration) => ({ ...integration, state: "operational" as const }));
}

// --- Tareas programadas (Cron) ------------------------------------------------------

export interface CronRow {
  id: string;
  name: string;
  cadence: string;
  /** Instante de la última ejecución; null mientras se está ejecutando. */
  lastRunAt: number | null;
  running: boolean;
}

/** Las tareas nocturnas se fijan a su hora del día (hoy si ya pasó, ayer si no);
 * las demás, a los minutos que dice la demostración. */
export function cronRows(now: number): CronRow[] {
  return DEMO_CRON.map((job) => {
    if (job.minutesAgo === null) {
      return { id: job.id, name: job.name, cadence: job.cadence, lastRunAt: null, running: true };
    }
    if (job.dailyAt) {
      const [hours, minutes] = job.dailyAt.split(":").map(Number);
      const dayStart = now - (now % DAY_MS);
      const today = dayStart + hours * HOUR_MS + minutes * 60_000;
      return { id: job.id, name: job.name, cadence: job.cadence, lastRunAt: today <= now ? today : today - DAY_MS, running: false };
    }
    return { id: job.id, name: job.name, cadence: job.cadence, lastRunAt: now - (job.minutesAgo ?? 0) * 60_000, running: false };
  });
}

// --- Base de datos: migraciones -----------------------------------------------------

export interface MigrationView {
  /** Versión aplicada: real cuando el backend la devuelve. */
  current: string;
  currentIsReal: boolean;
  previous: string;
  appliedAt: number;
  pending: number;
  failed: number;
}

export function migrationView(migration: string | null, now: number): MigrationView {
  return {
    current: migration ?? DEMO_MIGRATION_FALLBACK,
    currentIsReal: migration !== null,
    previous: DEMO_PREVIOUS_MIGRATION,
    appliedAt: now - DEMO_MIGRATION_HOURS_AGO * HOUR_MS,
    pending: DEMO_MIGRATIONS_PENDING,
    failed: DEMO_MIGRATIONS_FAILED,
  };
}

// --- Deployments --------------------------------------------------------------------

export interface DeploymentRow {
  version: string;
  environment: string;
  at: number;
  notes: string[];
}

export function deploymentRows(now: number): DeploymentRow[] {
  return DEMO_DEPLOYMENTS.map((deployment) => ({
    version: deployment.version,
    environment: deployment.environment,
    at: now - deployment.hoursAgo * HOUR_MS,
    notes: deployment.notes,
  }));
}

// --- Coste de infraestructura (hoy) -------------------------------------------------

export interface CostLine {
  id: string;
  label: string;
  amount: number;
  /** La inferencia de IA se estima sobre ejecuciones reales; el resto es demo. */
  isEstimate: boolean;
}

/** La línea de inferencia de IA usa las ejecuciones de hoy y el coste por equipo
 * de lib/demo/agents.ts: el mismo número que el coste de hoy de la pantalla de
 * Agentes. Las demás líneas son de demostración. */
export function costLines(agents: Agent[], executions: AgentExecution[], now: number): CostLine[] {
  const dayStart = now - (now % DAY_MS);
  const roleOf = new Map(agents.map((agent) => [agent.id, agent.role] as const));
  const inference = executions
    .filter((execution) => parseUtc(execution.created_at) >= dayStart)
    .reduce((sum, execution) => {
      const team = teamOf(roleOf.get(execution.agent_id) ?? "");
      return sum + (COST_PER_RUN[team] ?? COST_PER_RUN.Otros);
    }, 0);
  return [
    { id: "ai_inference", label: "AI inference", amount: round2(inference), isEstimate: true },
    ...DEMO_COST_LINES.map((line) => ({ ...line, isEstimate: false })),
  ];
}

export function costTotal(lines: CostLine[]): number {
  return round2(lines.reduce((sum, line) => sum + line.amount, 0));
}

// --- Incidentes ---------------------------------------------------------------------

export interface IncidentRow {
  id: string;
  code: string;
  title: string;
  open: boolean;
  at: number;
  /** Minutos hasta la resolución; null si sigue abierto. */
  resolvedInMinutes: number | null;
  isDemo: boolean;
}

export interface IncidentsView {
  rows: IncidentRow[];
  /** null cuando el backend no respondió: no es lo mismo que «cero». */
  open: number | null;
  total30d: number | null;
  /** true cuando la lista real está vacía y se enseñan los de demostración. */
  usingDemo: boolean;
  reachable: boolean;
}

/** Incidentes reales de los últimos 30 días; si el backend no tiene ninguno
 * registrado (se abren a mano), se enseñan los de demostración y se declara. */
export function incidentsView(incidents: Incident[] | null, now: number): IncidentsView {
  if (incidents === null) {
    return { rows: [], open: null, total30d: null, usingDemo: false, reachable: false };
  }
  const from = now - 30 * DAY_MS;
  const rows: IncidentRow[] = incidents
    .map((incident) => {
      const at = parseUtc(incident.created_at);
      const resolvedAt = incident.resolved_at ? parseUtc(incident.resolved_at) : null;
      return {
        id: incident.id,
        code: `INC-${incident.id.replace(/\D/g, "").slice(-4).padStart(4, "0")}`,
        title: incident.title,
        open: incident.status === "OPEN",
        at,
        resolvedInMinutes: resolvedAt === null ? null : Math.max(1, Math.round((resolvedAt - at) / 60_000)),
        isDemo: false,
      };
    })
    .filter((row) => row.at >= from)
    .sort((a, b) => b.at - a.at);
  const open = incidents.filter((incident) => incident.status === "OPEN").length;
  if (rows.length > 0) {
    return { rows, open, total30d: rows.length, usingDemo: false, reachable: true };
  }
  const demo: IncidentRow[] = DEMO_INCIDENTS.map((incident) => ({
    id: incident.code,
    code: incident.code,
    title: incident.title,
    open: false,
    at: now - incident.daysAgo * DAY_MS,
    resolvedInMinutes: incident.resolvedInMinutes,
    isDemo: true,
  }));
  return { rows: demo, open, total30d: 0, usingDemo: true, reachable: true };
}
