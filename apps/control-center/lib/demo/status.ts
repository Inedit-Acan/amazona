// DATOS DE DEMOSTRACIÓN — pantalla de Estado e infraestructura.
//
// Valores inventados (con permiso del propietario, 22-09-2026) para que el panel
// se vea como el mockup mientras el backend no los proporciona: `/health/detailed`
// solo dice si la base de datos responde, qué migración hay aplicada y si Supabase
// está configurado. No hay uptime, percentiles de latencia, series de las últimas
// 24 h, colas, tareas programadas, integraciones externas, métricas del motor de
// base de datos, despliegues ni costes de infraestructura. Deterministas por
// servicio y por hora (demoRandom), para que la pantalla no cambie sola entre el
// servidor y el cliente. Lo real —la comprobación de salud, el log de ejecuciones
// de agentes, el registro de agentes y los incidentes— se usa siempre que existe.
// Sustituir cuando existan los endpoints
// (docs/design/AMAZONA_estado_paneles_rediseno.md, sección 12).

import { demoRandom } from "./random.ts";

export const HOUR_MS = 3_600_000;

/** Horas de la serie «últimas 24 horas» de Métricas principales. */
export const METRIC_HOURS = 24;

export interface DemoService {
  id: string;
  name: string;
  /** Disponibilidad de los últimos 30 días (fracción). */
  uptime: number;
  /** Latencia p95 (ms); null cuando no aplica (copia de seguridad, certificados). */
  p95Ms: number | null;
}

/** Los 18 servicios de la spec (§9.5), con los valores del mockup. Solo seis
 * tienen señal real (ver `realSignals` en lib/status.ts); el resto se enseña
 * como demostración y la fila lo dice. */
export const DEMO_SERVICES: DemoService[] = [
  { id: "frontend", name: "Frontend", uptime: 0.9999, p95Ms: 98 },
  { id: "api", name: "API", uptime: 0.9998, p95Ms: 182 },
  { id: "postgres", name: "Postgres (Supabase)", uptime: 0.9999, p95Ms: 24 },
  { id: "auth", name: "Auth (Supabase)", uptime: 1, p95Ms: 36 },
  { id: "storage", name: "Storage", uptime: 1, p95Ms: 48 },
  { id: "realtime", name: "Realtime", uptime: 0.9997, p95Ms: 52 },
  { id: "edge_functions", name: "Edge Functions", uptime: 0.9996, p95Ms: 203 },
  { id: "workers", name: "Workers (Agentes)", uptime: 1, p95Ms: 118 },
  { id: "queue", name: "Queue (Redis)", uptime: 1, p95Ms: 12 },
  { id: "cron", name: "Scheduler / Cron", uptime: 1, p95Ms: 9 },
  { id: "integrations", name: "Integraciones externas", uptime: 0.9994, p95Ms: 264 },
  { id: "email", name: "Email Service", uptime: 1, p95Ms: 61 },
  { id: "monitoring", name: "Monitoring", uptime: 1, p95Ms: 22 },
  { id: "logs", name: "Logs", uptime: 1, p95Ms: 28 },
  { id: "backup", name: "Backup", uptime: 1, p95Ms: null },
  { id: "cdn", name: "CDN", uptime: 0.9994, p95Ms: 66 },
  { id: "dns", name: "DNS", uptime: 1, p95Ms: 17 },
  { id: "certificates", name: "Certificates", uptime: 1, p95Ms: null },
];

/** Puntos de la minitendencia de cada servicio (la columna sin ejes del mockup). */
export const TREND_POINTS = 16;

/** `demoRandom` mezcla poco los últimos caracteres de la semilla: con semillas que
 * solo se diferencian en el número final (la hora, el índice del punto) devuelve
 * valores casi iguales y las series salen escalonadas. Aquí la parte que cambia va
 * SIEMPRE delante, que es la que pasa por más rondas del hash. */
function demoNoise(varying: string | number, fixed: string): number {
  return demoRandom(String(varying), fixed);
}

/** Minitendencia de latencia de un servicio: ondula alrededor de su p95. */
export function demoTrend(serviceId: string, base: number): number[] {
  return Array.from({ length: TREND_POINTS }, (_, k) => Math.round(base * (0.78 + demoNoise(k, `trend-${serviceId}`) * 0.44)));
}

// --- System Health ------------------------------------------------------------------

/** Puntuaciones (0–100) de los bloques sin señal real. Los que sí la tienen
 * (API, Database, Auth, Storage y Workers) se calculan en lib/status-view.ts. */
export const DEMO_HEALTH_SCORES: Record<string, number> = {
  queues: 96,
  integrations: 97,
  security: 98,
  observability: 100,
};

export const HEALTH_NOTE = "Todo dentro de los rangos normales.";

// --- Agent Runtime ------------------------------------------------------------------

/** Ranuras de worker del runtime (el backend no publica un pool de workers). */
export const DEMO_WORKER_SLOTS = 10;

/** Colas de trabajo de los agentes, con su profundidad típica. */
export interface DemoQueue {
  id: string;
  /** Tareas en cola de referencia; la profundidad real se mueve ±2 por hora. */
  base: number;
}

export const DEMO_QUEUES: DemoQueue[] = [
  { id: "research_tasks", base: 3 },
  { id: "supplier_tasks", base: 1 },
  { id: "legal_tasks", base: 0 },
  { id: "marketing_tasks", base: 4 },
  { id: "operations_tasks", base: 6 },
];

export const DEMO_DEAD_LETTER = 1;

/** Profundidad de una cola en una hora dada: base ±2, nunca negativa. */
export function demoQueueDepth(queueId: string, hourKey: string): number {
  return Math.max(0, Math.round(DEMO_QUEUES.find((q) => q.id === queueId)!.base + demoNoise(hourKey, queueId) * 4 - 2));
}

/** Tiempo medio en cola (segundos) y antigüedad de la tarea más vieja. */
export const DEMO_QUEUE_WAIT_SECONDS = 1.8;
export const DEMO_OLDEST_TASK_SECONDS = 22;

/** Trabajos ejecutándose ahora mismo (sin telemetría de workers). */
export function demoRunningJobs(hourKey: string): number {
  return 9 + Math.round(demoNoise(hourKey, "running") * 6);
}

// --- Métricas principales -----------------------------------------------------------

/** Latencia p95 (ms) de la API en una hora concreta: base + un pico suave. */
export const DEMO_LATENCY_BASE_MS = 182;
export const DEMO_REQUESTS_PER_MINUTE = 2100;
export const DEMO_ERROR_RATE = 0.0012;

/** Variación 0,7–1,3 determinista de una métrica en una hora concreta. */
export function demoHourFactor(metric: string, hourKey: string): number {
  return 0.7 + demoNoise(hourKey, metric) * 0.6;
}

/** La tasa de errores va casi siempre baja con picos ocasionales, no ondula. */
export function demoErrorFactor(hourKey: string): number {
  return 0.4 + 4 * demoNoise(hourKey, "errors") ** 3;
}

/** Variación de los KPIs de cabecera respecto al periodo anterior. */
export const DEMO_KPI_DELTAS = {
  /** Puntos de disponibilidad ganados (fracción). */
  uptime: 0.0002,
  /** Variación relativa de la latencia p95 y de la tasa de errores. */
  p95: -0.12,
  errorRate: -0.68,
  /** Trabajos en cola respecto a la hora anterior. */
  queued: 2,
};

// --- Integraciones externas ---------------------------------------------------------

export interface DemoIntegration {
  id: string;
  name: string;
  latencyMs: number;
}

export const DEMO_INTEGRATIONS: DemoIntegration[] = [
  { id: "amazon_sp_api", name: "Amazon SP-API", latencyMs: 122 },
  { id: "google_ads", name: "Google Ads", latencyMs: 98 },
  { id: "meta_ads", name: "Meta Ads", latencyMs: 104 },
  { id: "stripe", name: "Stripe", latencyMs: 86 },
  { id: "google_shopping", name: "Google Shopping", latencyMs: 112 },
  { id: "shipping", name: "Shipping API", latencyMs: 156 },
  { id: "openai", name: "OpenAI", latencyMs: 203 },
];

// --- Tareas programadas (Cron) ------------------------------------------------------

export interface DemoCronJob {
  id: string;
  name: string;
  cadence: string;
  /** Minutos desde la última ejecución; null si está ejecutándose ahora. */
  minutesAgo: number | null;
  /** Hora fija del día (HH:MM) para las tareas nocturnas. */
  dailyAt?: string;
}

export const DEMO_CRON: DemoCronJob[] = [
  { id: "markets", name: "Actualizar mercados", cadence: "Cada hora", minutesAgo: 12 },
  { id: "suppliers", name: "Revisar proveedores", cadence: "Cada 6 h", minutesAgo: 27 },
  { id: "legal", name: "Legal monitor", cadence: "Cada 12 h", minutesAgo: 42 },
  { id: "cfo", name: "Forecast CFO", cadence: "Diario", minutesAgo: 57 },
  { id: "competitor", name: "Competitor scan", cadence: "Cada 4 h", minutesAgo: null },
  { id: "backup", name: "Database backup", cadence: "Diario", minutesAgo: 0, dailyAt: "04:00" },
];

export const DEMO_CRON_FAILURES_24H = 0;

// --- Base de datos (Supabase) -------------------------------------------------------

export const DEMO_DB_METRICS = {
  cpu: 0.34,
  memory: 0.48,
  connections: 42,
  maxConnections: 200,
  cacheHit: 0.994,
  slowQueries: 3,
  locks: 0,
  storage: 0.22,
  iops: "Normal",
};

// --- Deployments y migraciones ------------------------------------------------------

export interface DemoDeployment {
  version: string;
  environment: string;
  hoursAgo: number;
  notes: string[];
}

export const DEMO_DEPLOYMENTS: DemoDeployment[] = [
  { version: "v0.8.42", environment: "Producción", hoursAgo: 2, notes: ["Mejora en Agent Runtime", "Optimización de colas"] },
  { version: "v0.8.41", environment: "Producción", hoursAgo: 26, notes: ["Corrección en el registro de auditoría"] },
  { version: "v0.8.40", environment: "Producción", hoursAgo: 74, notes: ["Nuevos paneles de control"] },
];

/** Migración anterior y contadores: el backend solo devuelve la actual. */
export const DEMO_PREVIOUS_MIGRATION = "202609161822_add_audit_hash";
export const DEMO_MIGRATION_FALLBACK = "202609171142_add_agent_metrics";
export const DEMO_MIGRATIONS_PENDING = 0;
export const DEMO_MIGRATIONS_FAILED = 0;
export const DEMO_MIGRATION_HOURS_AGO = 2;

// --- Coste de infraestructura (hoy) -------------------------------------------------

/** Las líneas de coste que no dependen de los agentes; la de inferencia de IA se
 * calcula con las ejecuciones reales y el coste por equipo de lib/demo/agents.ts,
 * para que cuadre con el coste de hoy de la pantalla de Agentes. */
export const DEMO_COST_LINES = [
  { id: "database", label: "Database", amount: 1.18 },
  { id: "storage", label: "Storage", amount: 0.21 },
  { id: "functions", label: "Functions", amount: 0.84 },
  { id: "external_apis", label: "External APIs", amount: 2.42 },
];

// --- Incidentes ---------------------------------------------------------------------

export interface DemoIncident {
  code: string;
  title: string;
  /** Minutos que tardó en resolverse. */
  resolvedInMinutes: number;
  daysAgo: number;
}

/** Incidentes de los últimos 30 días cuando el backend no tiene ninguno
 * registrado (se registran a mano y hoy la lista suele estar vacía). */
export const DEMO_INCIDENTS: DemoIncident[] = [
  { code: "INC-0042", title: "Amazon SP-API rate limit", resolvedInMinutes: 14, daysAgo: 6 },
  { code: "INC-0041", title: "Database connection spike", resolvedInMinutes: 8, daysAgo: 19 },
];
