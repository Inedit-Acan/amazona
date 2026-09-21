import {
  Activity,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  Clock,
  Cloud,
  Database,
  FileText,
  GitBranch,
  Gauge,
  ListChecks,
  MinusCircle,
  Plug,
  ShieldAlert,
  Timer,
  XCircle,
} from "lucide-react";
import { ApiError, api, type AgentExecution, type DetailedHealth, type Incident } from "@/lib/api";
import { parseUtc } from "@/lib/dates";
import { formatDuration, formatInteger } from "@/lib/format";
import { overallStatus, serviceRows, serviceSummary, type HealthSignal, type ServiceState } from "@/lib/status";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { IncidentCard } from "@/components/incident-card";
import { IncidentReportForm } from "@/components/incident-report-form";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { ServiceMap, type ServiceMapNode } from "@/components/service-map";
import { StatusChip } from "@/components/status-chip";
import { VerdictBanner } from "@/components/verdict-banner";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const PENDING_INFRA: PendingFeature[] = [
  {
    icon: Gauge,
    title: "Uptime, API p50/p95/p99 y errores 5xx",
    description: "Disponibilidad a 30 días, latencias por percentil, requests/min, 2xx/4xx/5xx y error budget.",
  },
  {
    icon: Boxes,
    title: "Los otros 14 servicios",
    description: "Auth, Storage, Realtime, Edge Functions, Workers, Queue, Cron, Email, Monitoring, Logs, Backup, CDN, DNS y certificados.",
  },
  {
    icon: ListChecks,
    title: "Colas, workers y cron",
    description: "Tasks pendientes, dead-letter, tarea más antigua, workers activos y estado de las tareas programadas.",
  },
  {
    icon: Plug,
    title: "Integraciones y rate limits",
    description: "Estado, latencia, errores y consumo de límites de Stripe, Google/Meta Ads, Amazon SP-API, OpenAI…",
  },
  {
    icon: Database,
    title: "Métricas de la base de datos",
    description: "CPU, memoria, conexiones, cache hit, queries lentas, locks, storage e IOPS.",
  },
  {
    icon: GitBranch,
    title: "Deployments y migraciones",
    description: "Versión desplegada, fecha, commit y estado; migraciones anteriores, pendientes y fallidas.",
  },
  {
    icon: CircleDollarSign,
    title: "Coste técnico",
    description: "Inferencia de IA, base de datos, storage, functions y APIs externas.",
  },
  {
    icon: FileText,
    title: "Logs Explorer y status público",
    description: "Logs técnicos filtrables por servicio, nivel, request y correlación; página de estado pública.",
  },
];

const STATE_LABEL: Record<ServiceState, string> = { operational: "Operativo", down: "Caído", no_signal: "Sin telemetría" };

/** Estado con icono y texto: nunca depende solo del color (spec §9.4). */
function ServiceStateBadge({ state }: { state: ServiceState }) {
  const Icon = state === "operational" ? CheckCircle2 : state === "down" ? XCircle : MinusCircle;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-sm font-medium",
        state === "operational" && "text-primary",
        state === "down" && "text-red-500",
        state === "no_signal" && "text-muted-foreground",
      )}
    >
      <Icon className="size-4" /> {STATE_LABEL[state]}
    </span>
  );
}

const STATUS_KPI_TONE: Record<"ok" | "warn" | "bad", KpiTone> = { ok: "success", warn: "warning", bad: "danger" };

/** La comprobación de salud se mide desde el servidor del frontend: una sola medida, no un percentil. */
async function fetchHealth(): Promise<HealthSignal & { migration: string | null }> {
  const started = Date.now();
  try {
    const health = await api.getHealth();
    return { apiReachable: true, latencyMs: Date.now() - started, health, migration: health.migration };
  } catch (err) {
    if (err instanceof ApiError) {
      try {
        // /health/detailed responde 503 con el mismo cuerpo cuando la base de datos falla
        const health = JSON.parse(err.message) as DetailedHealth;
        return { apiReachable: true, latencyMs: Date.now() - started, health, migration: health.migration };
      } catch {
        // cae al estado de backend inalcanzable
      }
    }
    return { apiReachable: false, latencyMs: null, health: { database: "error", supabase_configured: false }, migration: null };
  }
}

export default async function StatusPage() {
  const [signal, executions, incidents] = await Promise.all([
    fetchHealth(),
    // null = la petición falló: no es lo mismo que «cero» y no se muestra como tal
    api.listAgentExecutions().catch((): AgentExecution[] | null => null),
    api.listIncidents().catch((): Incident[] | null => null),
  ]);
  const openIncidents = (incidents ?? []).filter((i) => i.status === "OPEN");
  const resolvedIncidents = (incidents ?? []).filter((i) => i.status === "RESOLVED");
  const rows = serviceRows(signal);
  const summary = serviceSummary(rows);
  const overall = overallStatus({ signal, openIncidents: openIncidents.length });
  const failedRuns = (executions ?? []).filter((e) => !e.success).length;

  const serviceMapNodes: ServiceMapNode[] = [
    { id: "users", label: "Usuarios", status: "idle", note: "No hay telemetría de tráfico real todavía" },
    { id: "frontend", label: "Frontend", status: "active" },
    {
      id: "api",
      label: "API",
      status: signal.apiReachable ? "active" : "error",
      note: signal.apiReachable ? undefined : "No se pudo contactar al backend",
    },
    {
      id: "database",
      label: "Postgres",
      status: !signal.apiReachable ? "idle" : signal.health.database === "ok" ? "active" : "error",
      note: signal.apiReachable ? undefined : "Sin respuesta del backend",
    },
    {
      id: "auth_storage",
      label: "Auth / Storage",
      status: signal.apiReachable && signal.health.supabase_configured ? "active" : "idle",
      note: !signal.apiReachable ? "Sin respuesta del backend" : signal.health.supabase_configured ? undefined : "Supabase no configurado",
    },
    { id: "queue", label: "Cola", status: "idle", note: "Sin endpoint de monitorización de cola todavía" },
    { id: "workers", label: "Procesos", status: "idle", note: "Sin telemetría de procesos todavía" },
    { id: "integrations", label: "Integraciones externas", status: "idle", note: "Sin monitorización de integraciones todavía" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Estado e infraestructura"
        description="Salud de la infraestructura que hace funcionar AMAZONA, medida en esta carga de la página. Es una señal puntual, no un historial: sin datos de negocio (para eso está Auditoría) ni calidad de agentes (Agentes)."
      />

      {/* Prioridad visual superior: cualquier problema real se ve antes que el resto. */}
      <VerdictBanner tone={overall.tone} title={overall.title} detail={overall.detail} />

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores de infraestructura">
        <KpiCard
          label="Estado general"
          value={overall.title}
          icon={ShieldAlert}
          tone={STATUS_KPI_TONE[overall.tone]}
          caption="A partir de la señal real disponible"
          provenance="verified"
          provenanceTooltip="Se calcula con la comprobación de salud y los incidentes abiertos."
        />
        <KpiCard
          label="Servicios con señal"
          value={`${summary.operational}/${summary.withSignal}`}
          icon={Cloud}
          caption="Operativos de los que se pueden medir"
          provenance="verified"
          provenanceTooltip="Frontend, API, base de datos y configuración de Supabase. El resto de servicios no tiene telemetría."
        />
        <KpiCard
          label="Latencia de la API"
          value={signal.latencyMs !== null ? formatDuration(signal.latencyMs) : "—"}
          icon={Timer}
          caption="Una medida de la comprobación de salud"
          provenance={signal.latencyMs !== null ? "verified" : "pending"}
          provenanceTooltip="Tiempo de esta petición desde el servidor del frontend; no es un percentil p95."
        />
        <KpiCard
          label="Incidentes activos"
          value={incidents ? formatInteger(openIncidents.length) : "—"}
          icon={Activity}
          tone={openIncidents.length > 0 ? "warning" : "default"}
          caption={
            incidents
              ? `${resolvedIncidents.length} resuelto${resolvedIncidents.length === 1 ? "" : "s"}`
              : "No se pudieron cargar"
          }
          provenance={incidents ? "verified" : "pending"}
          provenanceTooltip="Incidentes registrados a mano; no se generan automáticamente."
        />
        <KpiCard
          label="Migración"
          value={signal.migration ?? "—"}
          icon={GitBranch}
          caption={signal.migration ? "Versión del esquema" : "Sin versión de esquema (base sin migraciones)"}
          provenance={signal.migration ? "verified" : "pending"}
        />
        <KpiCard
          label="Ejecuciones de agentes"
          value={executions ? formatInteger(executions.length) : "—"}
          icon={Clock}
          tone={failedRuns > 0 ? "danger" : "default"}
          caption={executions ? `${failedRuns} fallida${failedRuns === 1 ? "" : "s"} (últimas 100)` : "No se pudieron cargar"}
          provenance={executions ? "verified" : "pending"}
        />
      </section>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Servicios</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="verified" tooltip="Comprobación de salud hecha al cargar esta página." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Servicio</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead className="text-right">Latencia</TableHead>
                    <TableHead>Detalle</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell>
                        <ServiceStateBadge state={row.state} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{row.latencyMs !== null ? formatDuration(row.latencyMs) : "—"}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{row.note}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Solo se listan los servicios de los que hay señal real. Uptime, latencia por servicio y los otros 14
              servicios de la spec: sin telemetría (abajo).
            </p>
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Mapa de servicios</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <ServiceMap nodes={serviceMapNodes} />
            <p className="text-[11px] text-muted-foreground">
              Verde: hay señal y responde · rojo: falla · gris: sin telemetría (pasa el cursor para ver el motivo).
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Incidentes</CardTitle>
            <CardAction>{openIncidents.length > 0 ? <StatusChip status="OPEN" /> : null}</CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <IncidentReportForm />

            {!incidents ? (
              <p className="text-sm text-muted-foreground">No se pudieron cargar los incidentes: el backend no responde.</p>
            ) : openIncidents.length > 0 ? (
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
            <p className="text-[11px] text-muted-foreground">
              Los incidentes se registran a mano: el sistema no los abre solo. Causa, impacto y duración: pendientes.
            </p>
          </CardContent>
        </Card>

        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Base de datos</CardTitle>
            <CardAction>
              <ServiceStateBadge state={!signal.apiReachable ? "no_signal" : signal.health.database === "ok" ? "operational" : "down"} />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="divide-y text-sm">
              <div className="flex justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">Migración</dt>
                <dd className="font-mono text-xs">{signal.migration ?? "—"}</dd>
              </div>
              <div className="flex items-center justify-between gap-3 py-1.5">
                <dt className="text-muted-foreground">Supabase</dt>
                <dd>
                  {signal.apiReachable ? (
                    <StatusChip status={signal.health.supabase_configured ? "AVAILABLE" : "DISABLED"} />
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
            </dl>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <DataProvenanceBadge status="pending" tooltip="El backend no expone métricas del motor de base de datos." />
              CPU, memoria, conexiones, cache hit, queries lentas, locks, storage e IOPS.
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ejecuciones recientes de agentes</CardTitle>
          <CardAction>
            <DataProvenanceBadge
              status={executions ? "verified" : "pending"}
              tooltip="Últimas filas del log de ejecuciones de agentes."
            />
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-3">
          {!executions ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No se pudieron cargar las ejecuciones: el backend no responde.</p>
          ) : executions.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Todavía no hay ejecuciones de agentes registradas.</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cuándo</TableHead>
                    <TableHead>Agente</TableHead>
                    <TableHead>Capacidad</TableHead>
                    <TableHead>Duración</TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {executions.slice(0, 10).map((e) => (
                    <TableRow key={e.id}>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {new Date(parseUtc(e.created_at)).toLocaleString("es-ES")}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{e.agent_id}</TableCell>
                      <TableCell className="text-sm">{e.capability}</TableCell>
                      <TableCell className="text-sm tabular-nums">{formatDuration(e.duration_ms)}</TableCell>
                      <TableCell>
                        <StatusChip status={e.success ? "COMPLETED" : "FAILED"} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">
            Solo la parte de infraestructura: las diez más recientes. El rendimiento y la calidad de cada agente están en
            Agentes. Workers, jobs y colas: pendientes.
          </p>
        </CardContent>
      </Card>

      <PendingFeatures
        title="System Operations Center — pendiente de backend"
        tooltip="El backend solo expone una comprobación de salud (base de datos, migración y configuración de Supabase)."
        items={PENDING_INFRA}
        columns={4}
        note="Estado e infraestructura hoy es una comprobación puntual al cargar la página, no monitorización continua: no hay series temporales, colas, cron, integraciones, despliegues ni costes. Hasta que exista, no se muestra ningún uptime, percentil ni «18/18 servicios operativos»."
      />
    </div>
  );
}
