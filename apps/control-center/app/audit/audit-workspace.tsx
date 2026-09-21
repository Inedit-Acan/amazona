"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileArchive,
  FileText,
  Fingerprint,
  Gavel,
  HardDrive,
  ScrollText,
  Search,
  ShieldAlert,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { AuditEntry } from "@/lib/api";
import {
  EVENT_CATEGORIES,
  actorKind,
  actorRows,
  auditSummary,
  eventCategory,
  filterEvents,
  groupByDay,
  projectRows,
  stateChanges,
  unattributedCount,
  type ActorRow,
  type AuditFilters,
  type ProjectByCorrelation,
  type ProjectRow,
} from "@/lib/audit";
import { parseUtc } from "@/lib/dates";
import { formatInteger } from "@/lib/format";
import { CorrelationTrace } from "@/components/correlation-trace";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 12;
const INPUT_CLASS = "rounded-md border bg-background px-3 py-1.5 text-sm";
/** El backend devuelve como máximo 500 eventos, los más antiguos primero (api/audit.py). */
const API_LIMIT = 500;

const PENDING_INTEGRITY: PendingFeature[] = [
  {
    icon: Fingerprint,
    title: "Integridad y cadena de hashes",
    description: "Hash por evento, cadena de hashes, última verificación y eventos modificados = 0.",
  },
  {
    icon: FileArchive,
    title: "Evidencias asociadas",
    description: "Informes, Legal Gate, presupuesto, aprobaciones y documentos con hash, versión y estado.",
  },
  {
    icon: ShieldAlert,
    title: "Anomalías",
    description: "Precio cambiado sin aprobación, acción fuera de política o proveedor modificado tras aprobar.",
  },
  {
    icon: Gavel,
    title: "Criticidad y resultado",
    description: "Cada evento con su criticidad (crítica/alta/media/baja) y su resultado (éxito, error, creado).",
  },
];

const PENDING_RETENTION: PendingFeature[] = [
  {
    icon: HardDrive,
    title: "Retención por tipo de evento",
    description: "Cuánto se conserva cada tipo de evento y cuándo se archiva.",
  },
  {
    icon: FileText,
    title: "Exportación completa y paquete de auditoría",
    description: "JSON, PDF de evidencia y paquete por proyecto/periodo con eventos, aprobaciones, evidencias y hashes.",
  },
];

const WINDOW_OPTIONS: { value: AuditFilters["window"]; label: string }[] = [
  { value: "all", label: "Todo el histórico" },
  { value: "24h", label: "Últimas 24 h" },
  { value: "7d", label: "Últimos 7 días" },
  { value: "30d", label: "Últimos 30 días" },
];

const CATEGORY_TONE: Record<string, string> = {
  Aprobación: "border-amber-500/40 text-amber-500",
  Decisión: "border-primary/50 text-primary",
  Seguridad: "border-red-500/40 text-red-500",
  Incidencia: "border-red-500/40 text-red-500",
};

function CategoryChip({ action }: { action: string }) {
  const category = eventCategory(action);
  return (
    <Badge variant="outline" className={cn("font-medium", CATEGORY_TONE[category])}>
      {category}
    </Badge>
  );
}

function formatDateTime(value: string): string {
  return new Date(parseUtc(value)).toLocaleString("es-ES");
}

function formatMs(ms: number): string {
  return new Date(ms).toLocaleString("es-ES");
}

export function AuditWorkspace({
  entries,
  projects,
  correlationId,
}: {
  entries: AuditEntry[];
  projects: ProjectByCorrelation;
  correlationId?: string;
}) {
  // Se fija una vez: mantiene el render puro y estable.
  const [now] = useState(() => Date.now());
  const [filters, setFilters] = useState<AuditFilters>({ window: "all", category: "all", actor: "all", project: "all", query: "" });
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const summary = useMemo(() => auditSummary(entries, now), [entries, now]);
  const newestFirst = useMemo(() => [...entries].sort((a, b) => parseUtc(b.created_at) - parseUtc(a.created_at)), [entries]);
  const filtered = useMemo(() => filterEvents(newestFirst, filters, projects, now), [newestFirst, filters, projects, now]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const actorOptions = useMemo(() => [...new Set(entries.map((e) => e.actor))].sort(), [entries]);
  const projectOptions = useMemo(
    () => [...new Map(Object.values(projects).map((p) => [p.id, p.name] as const)).entries()].sort((a, b) => a[1].localeCompare(b[1], "es")),
    [projects],
  );
  const actors = useMemo(() => actorRows(entries), [entries]);
  const byProject = useMemo(() => projectRows(entries, projects), [entries, projects]);
  const unattributed = useMemo(() => unattributedCount(entries, projects), [entries, projects]);
  const days = useMemo(() => groupByDay(entries).slice(0, 7), [entries]);
  const humanEvents = useMemo(() => newestFirst.filter((e) => actorKind(e.actor) === "Persona"), [newestFirst]);

  const selected = entries.find((e) => e.id === selectedId) ?? filtered[0];
  const trace = selected ? entries.filter((e) => e.correlation_id === selected.correlation_id) : [];
  const selectedProject = selected ? projects[selected.correlation_id] : undefined;
  const changes = selected ? stateChanges(selected.before, selected.after) : [];

  function update(patch: Partial<AuditFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
    setPage(0);
  }

  const eventColumns: DataTableColumn<AuditEntry>[] = [
    { key: "when", header: "Fecha y hora", cell: (row) => <span className="text-xs whitespace-nowrap">{formatDateTime(row.created_at)}</span>, sortValue: (row) => row.created_at, exportValue: (row) => row.created_at },
    { key: "type", header: "Tipo", cell: (row) => <CategoryChip action={row.action} />, sortValue: (row) => eventCategory(row.action), exportValue: (row) => eventCategory(row.action) },
    { key: "action", header: "Acción", cell: (row) => <span className="font-medium">{row.action}</span>, sortValue: (row) => row.action, exportValue: (row) => row.action },
    { key: "actor", header: "Actor", cell: (row) => <span className="font-mono text-xs">{row.actor}</span>, sortValue: (row) => row.actor, exportValue: (row) => row.actor },
    {
      key: "project",
      header: "Proyecto",
      cell: (row) => projects[row.correlation_id]?.name ?? <span className="text-muted-foreground">—</span>,
      exportValue: (row) => projects[row.correlation_id]?.name ?? "",
    },
    { key: "resource", header: "Recurso", cell: (row) => <span className="font-mono text-[11px] text-muted-foreground">{row.resource}</span>, exportValue: (row) => row.resource },
    { key: "corr", header: "Correlación", cell: (row) => <span className="font-mono text-[11px]">{row.correlation_id.slice(0, 8)}</span>, exportValue: (row) => row.correlation_id },
  ];

  const actorColumns: DataTableColumn<ActorRow>[] = [
    { key: "actor", header: "Actor", cell: (row) => <span className="font-mono text-xs">{row.actor}</span>, sortValue: (row) => row.actor, exportValue: (row) => row.actor },
    { key: "kind", header: "Tipo", cell: (row) => row.kind, sortValue: (row) => row.kind, exportValue: (row) => row.kind },
    { key: "events", header: "Eventos", cell: (row) => formatInteger(row.events), sortValue: (row) => row.events, exportValue: (row) => row.events, align: "right" },
    { key: "errors", header: "Errores", cell: (row) => <span className={cn(row.errors > 0 && "font-medium text-destructive")}>{row.errors}</span>, sortValue: (row) => row.errors, align: "right" },
    { key: "first", header: "Primer evento", cell: (row) => <span className="text-xs">{formatMs(row.firstAt)}</span>, sortValue: (row) => row.firstAt },
    { key: "last", header: "Último evento", cell: (row) => <span className="text-xs">{formatMs(row.lastAt)}</span>, sortValue: (row) => row.lastAt },
  ];

  const projectColumns: DataTableColumn<ProjectRow>[] = [
    {
      key: "name",
      header: "Proyecto",
      cell: (row) => (
        <Link href={`/projects/${row.projectId}`} className="font-medium text-primary underline-offset-4 hover:underline">
          {row.name}
        </Link>
      ),
      sortValue: (row) => row.name,
      exportValue: (row) => row.name,
    },
    { key: "events", header: "Eventos", cell: (row) => formatInteger(row.events), sortValue: (row) => row.events, exportValue: (row) => row.events, align: "right" },
    { key: "corr", header: "Ejecuciones", cell: (row) => formatInteger(row.correlations), sortValue: (row) => row.correlations, align: "right" },
    { key: "last", header: "Último evento", cell: (row) => <span className="text-xs">{formatMs(row.lastAt)}</span>, sortValue: (row) => row.lastAt },
  ];

  if (entries.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={ScrollText}
            title={correlationId ? "No hay eventos para este ID de correlación" : "Todavía no hay eventos de auditoría"}
            description={
              correlationId
                ? "Ese ID no aparece en el registro."
                : "Cada acción relevante de los agentes, el director ejecutivo y las personas queda registrada aquí."
            }
            action={
              correlationId ? (
                <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/audit" />}>
                  Ver todo el registro
                </Button>
              ) : undefined
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {correlationId ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
          <span>
            Mostrando solo los eventos del ID de correlación <span className="font-mono text-xs">{correlationId}</span>.
          </span>
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/audit" />}>
            <ArrowLeft /> Ver todo el registro
          </Button>
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores de auditoría">
        <KpiCard
          label="Eventos registrados"
          value={formatInteger(summary.total)}
          icon={ScrollText}
          caption={summary.total >= API_LIMIT && !correlationId ? `Límite de ${API_LIMIT}: puede haber más` : "En el registro"}
          provenance="verified"
        />
        <KpiCard label="Eventos hoy" value={formatInteger(summary.today)} icon={Clock} caption="Del día actual" provenance="verified" />
        <KpiCard label="Aprobaciones" value={formatInteger(summary.approvals)} icon={CheckCheck} caption="Solicitadas y resueltas" provenance="verified" />
        <KpiCard label="Decisiones del CEO" value={formatInteger(summary.decisions)} icon={Gavel} caption="Decisiones registradas" provenance="verified" />
        <KpiCard
          label="Errores"
          value={formatInteger(summary.errors)}
          icon={AlertTriangle}
          tone={summary.errors > 0 ? "danger" : "default"}
          caption="Acciones que indican un fallo"
          provenance="verified"
        />
        <KpiCard
          label="Acciones críticas"
          value="—"
          icon={ShieldAlert}
          caption="Los eventos no tienen criticidad"
          provenance="pending"
          provenanceTooltip="El registro no clasifica los eventos por criticidad."
        />
      </section>

      <Tabs defaultValue="events" className="gap-4">
        <div className="max-w-full overflow-x-auto">
          <TabsList>
            <TabsTrigger value="events">Eventos</TabsTrigger>
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="projects">Proyectos</TabsTrigger>
            <TabsTrigger value="agents">Agentes</TabsTrigger>
            <TabsTrigger value="security">Seguridad</TabsTrigger>
            <TabsTrigger value="integrity">Integridad</TabsTrigger>
            <TabsTrigger value="retention">Retención</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="events" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-8">
              <CardHeader>
                <CardTitle>Eventos</CardTitle>
                <CardAction>
                  <DataProvenanceBadge status="verified" tooltip="Filas del registro de auditoría de la base de datos." />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <select value={filters.window} onChange={(e) => update({ window: e.target.value as AuditFilters["window"] })} aria-label="Periodo" className={INPUT_CLASS}>
                    {WINDOW_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <select value={filters.category} onChange={(e) => update({ category: e.target.value as AuditFilters["category"] })} aria-label="Tipo de evento" className={INPUT_CLASS}>
                    <option value="all">Todos los tipos</option>
                    {EVENT_CATEGORIES.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>
                  <select value={filters.actor} onChange={(e) => update({ actor: e.target.value })} aria-label="Actor" className={cn(INPUT_CLASS, "max-w-48")}>
                    <option value="all">Todos los actores</option>
                    {actorOptions.map((actor) => (
                      <option key={actor} value={actor}>
                        {actor}
                      </option>
                    ))}
                  </select>
                  <select value={filters.project} onChange={(e) => update({ project: e.target.value })} aria-label="Proyecto" className={cn(INPUT_CLASS, "max-w-48")}>
                    <option value="all">Todos los proyectos</option>
                    {projectOptions.map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <label className="relative block min-w-40 flex-1">
                    <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="search"
                      value={filters.query}
                      onChange={(e) => update({ query: e.target.value })}
                      placeholder="Buscar eventos, ID, texto…"
                      aria-label="Buscar eventos"
                      className={cn(INPUT_CLASS, "w-full pl-9")}
                    />
                  </label>
                </div>

                <DataTable
                  columns={eventColumns}
                  rows={pageRows}
                  getRowId={(row) => row.id}
                  selectedId={selected?.id ?? null}
                  onSelect={(row) => setSelectedId(row.id)}
                  exportFileName="auditoria.csv"
                  emptyMessage="Ningún evento coincide con los filtros."
                />

                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {filtered.length === 0
                      ? "0 eventos"
                      : `Mostrando ${currentPage * PAGE_SIZE + 1}–${Math.min((currentPage + 1) * PAGE_SIZE, filtered.length)} de ${formatInteger(filtered.length)} eventos`}
                    {" · "}
                    la exportación CSV incluye solo la página visible
                  </span>
                  <div className="flex items-center gap-1">
                    <Button type="button" size="icon-sm" variant="outline" aria-label="Página anterior" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>
                      <ChevronLeft />
                    </Button>
                    <span className="tabular-nums">
                      {currentPage + 1} / {pageCount}
                    </span>
                    <Button type="button" size="icon-sm" variant="outline" aria-label="Página siguiente" disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)}>
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-4">
              <CardHeader>
                <CardTitle>Detalle del evento</CardTitle>
                <CardAction>
                  <DataProvenanceBadge status="verified" tooltip="Evento leído del registro de auditoría." />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                {selected ? (
                  <>
                    <div>
                      <p className="text-base font-semibold">{selected.action}</p>
                      <p className="text-xs text-muted-foreground">{formatDateTime(selected.created_at)}</p>
                    </div>
                    <dl className="divide-y rounded-lg border px-3 text-sm">
                      {[
                        ["ID del evento", <span key="id" className="font-mono text-xs">{selected.id.slice(0, 13)}</span>],
                        ["Tipo", <CategoryChip key="type" action={selected.action} />],
                        ["Actor", `${selected.actor} (${actorKind(selected.actor).toLowerCase()})`],
                        ["Recurso", <span key="res" className="font-mono text-xs break-all">{selected.resource}</span>],
                        [
                          "Proyecto",
                          selectedProject ? (
                            <Link key="proj" href={`/projects/${selectedProject.id}`} className="text-primary underline-offset-4 hover:underline">
                              {selectedProject.name}
                            </Link>
                          ) : (
                            "—"
                          ),
                        ],
                        [
                          "Correlación",
                          <Link key="corr" href={`/audit?correlation_id=${selected.correlation_id}`} className="font-mono text-xs text-primary underline-offset-4 hover:underline">
                            {selected.correlation_id.slice(0, 13)}
                          </Link>,
                        ],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="flex items-start justify-between gap-3 py-1.5">
                          <dt className="text-muted-foreground">{label}</dt>
                          <dd className="text-right font-medium">{value}</dd>
                        </div>
                      ))}
                    </dl>

                    <div>
                      <p className="mb-1.5 text-xs font-medium text-muted-foreground">Antes / después</p>
                      {changes.length > 0 ? (
                        <div className="overflow-x-auto rounded-lg border">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b text-left text-muted-foreground">
                                <th className="px-2 py-1.5 font-medium">Campo</th>
                                <th className="px-2 py-1.5 font-medium">Antes</th>
                                <th className="px-2 py-1.5 font-medium">Después</th>
                              </tr>
                            </thead>
                            <tbody>
                              {changes.map((change) => (
                                <tr key={change.key} className="border-b last:border-0">
                                  <td className="px-2 py-1.5 font-mono">{change.key}</td>
                                  <td className="px-2 py-1.5 font-mono break-all text-red-400">{change.before ?? "—"}</td>
                                  <td className="px-2 py-1.5 font-mono break-all text-primary">{change.after ?? "—"}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">Este evento no guarda estado antes ni después.</p>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                      <DataProvenanceBadge status="pending" tooltip="El registro no guarda origen, IP ni user agent del evento." />
                      Origen del evento, IP, user agent, resultado y criticidad: sin datos.
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Selecciona un evento de la tabla.</p>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Trazabilidad (Correlation Trace)</CardTitle>
              <CardAction>
                <DataProvenanceBadge status="verified" tooltip="Todos los eventos que comparten el ID de correlación del evento elegido, en orden cronológico." />
              </CardAction>
            </CardHeader>
            <CardContent>
              {trace.length > 0 ? (
                <CorrelationTrace entries={trace} />
              ) : (
                <p className="text-sm text-muted-foreground">Elige un evento para ver todo lo que ocurrió bajo su ID de correlación.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="timeline" className="space-y-4">
          {days.map((group) => (
            <Card key={group.day}>
              <CardHeader>
                <CardTitle>{new Date(`${group.day}T12:00:00`).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</CardTitle>
                <CardAction>
                  <span className="text-xs text-muted-foreground">{group.entries.length} eventos</span>
                </CardAction>
              </CardHeader>
              <CardContent>
                <ol className="space-y-2 border-l pl-4">
                  {group.entries.slice(0, 40).map((entry) => (
                    <li key={entry.id} className="relative flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                      <span className="absolute top-2 -left-[21px] size-2 rounded-full bg-primary" aria-hidden />
                      <span className="w-16 shrink-0 text-xs tabular-nums text-muted-foreground">
                        {new Date(parseUtc(entry.created_at)).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                      </span>
                      <span className="font-medium">{entry.action}</span>
                      <span className="font-mono text-xs text-muted-foreground">{entry.actor}</span>
                      {projects[entry.correlation_id] ? <span className="text-xs text-muted-foreground">· {projects[entry.correlation_id].name}</span> : null}
                    </li>
                  ))}
                </ol>
                {group.entries.length > 40 ? <p className="mt-2 text-xs text-muted-foreground">Se muestran los 40 más recientes del día.</p> : null}
              </CardContent>
            </Card>
          ))}
          <p className="text-[11px] text-muted-foreground">Últimos 7 días con actividad.</p>
        </TabsContent>

        <TabsContent value="projects" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Actividad por proyecto</CardTitle>
              <CardAction>
                <Users className="size-4 text-primary" />
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-3">
              <DataTable columns={projectColumns} rows={byProject} getRowId={(row) => row.projectId} exportFileName="auditoria-proyectos.csv" emptyMessage="Ningún evento se puede atribuir a un proyecto." />
              <p className="text-[11px] text-muted-foreground">
                El evento no guarda el proyecto: se atribuye por el ID de correlación de la decisión del proyecto.
                {unattributed > 0 ? ` ${formatInteger(unattributed)} eventos (análisis por producto, memoria…) no se pueden atribuir a un proyecto.` : ""}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="agents" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Actividad por actor</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <DataTable columns={actorColumns} rows={actors} getRowId={(row) => row.actor} getSearchText={(row) => row.actor} searchPlaceholder="Buscar actor…" exportFileName="auditoria-actores.csv" />
              <p className="text-[11px] text-muted-foreground">
                El tipo de actor se deduce del nombre (agente, persona, orquestador o sistema). Cambios de versión, aprobaciones
                por agente e incidencias: pendientes.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="security" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Acciones de personas</CardTitle>
              <CardAction>
                <ShieldCheck className="size-4 text-primary" />
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-3">
              {humanEvents.length > 0 ? (
                <DataTable
                  columns={eventColumns.filter((c) => c.key !== "project")}
                  rows={humanEvents}
                  getRowId={(row) => row.id}
                  exportFileName="auditoria-personas.csv"
                />
              ) : (
                <p className="text-sm text-muted-foreground">Todavía no hay acciones de personas en el registro.</p>
              )}
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                <DataProvenanceBadge status="pending" tooltip="El backend no registra inicios de sesión, permisos, API keys ni integraciones." />
                Inicios de sesión, permisos, API keys, integraciones, owner y políticas: no se auditan todavía.
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="integrity" className="space-y-4">
          <PendingFeatures
            title="Integridad y evidencias — pendiente de backend"
            tooltip="El registro no calcula hashes, no guarda evidencias ni detecta anomalías."
            items={PENDING_INTEGRITY}
            columns={4}
            note="Los eventos se guardan como filas de una tabla. La interfaz no permite editarlos ni borrarlos, pero el backend no encadena hashes ni verifica que nadie los haya modificado, así que no se puede afirmar integridad demostrable."
          />
        </TabsContent>

        <TabsContent value="retention" className="space-y-4">
          <PendingFeatures
            title="Retención y exportación — pendiente de backend"
            tooltip="No hay política de retención ni generación de paquetes de auditoría."
            items={PENDING_RETENTION}
            note="Sí se puede exportar a CSV la tabla de eventos (solo la página visible) y las tablas de actores y proyectos."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
