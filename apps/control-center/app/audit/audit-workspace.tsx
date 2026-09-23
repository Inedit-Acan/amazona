"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CircleCheck,
  Download,
  FileText,
  Package,
  Settings2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import type { Agent, AuditEntry, Product } from "@/lib/api";
import {
  EMPTY_FILTERS,
  WINDOW_LABELS,
  anomalies,
  auditKpis,
  auditRows,
  correlationTrace,
  filterOptions,
  filterRows,
  paginate,
  type AuditRow,
  type AuditWindow,
  type RowFilters,
} from "@/lib/audit-view";
import { EXPORT_FORMATS } from "@/lib/demo/audit";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatInteger, formatPercent } from "@/lib/format";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { AUDIT_DESCRIPTION, AUDIT_TITLE } from "./copy";
import {
  ActorsTabCard,
  AnomaliesCard,
  ChangesCard,
  EventFieldsCard,
  EvidencesCard,
  IntegrityCard,
  IntegrityTabCard,
  JsonCard,
  ProjectContextCard,
  ProjectsTabCard,
  RetentionTabCard,
  SecurityTabCard,
  TimelineCard,
  TraceCard,
  formatDateTime,
} from "./audit-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: una entrada real del registro solo guarda actor, acción, recurso, estado antes/después, ID de correlación y fecha, y hoy hay poco más de una decena. Los eventos que llenan la tabla, la criticidad, la IP, el user agent, las evidencias, el hash de integridad, las anomalías y la política de retención son simulados. Real: las entradas del backend, su tipo y actor deducidos de la acción, sus cambios de estado y su cadena de correlación.";

const MAIN_TABS = [
  { key: "eventos", label: "Eventos" },
  { key: "timeline", label: "Timeline" },
  { key: "proyectos", label: "Proyectos" },
  { key: "agentes", label: "Agentes" },
  { key: "seguridad", label: "Seguridad" },
  { key: "integridad", label: "Integridad" },
  { key: "retencion", label: "Retención" },
] as const;

type MainTab = (typeof MAIN_TABS)[number]["key"];

const DETAIL_TABS = [
  { key: "resumen", label: "Resumen" },
  { key: "datos", label: "Datos" },
  { key: "evidencias", label: "Evidencias" },
  { key: "trazabilidad", label: "Trazabilidad" },
  { key: "json", label: "JSON" },
] as const;

type DetailTab = (typeof DETAIL_TABS)[number]["key"];

const RESULT_TONE: Record<AuditRow["result"], LevelTone> = { "Éxito": "ok", Creado: "neutral", Error: "bad" };
const CRITICALITY_TONE: Record<AuditRow["criticality"], LevelTone> = { Alta: "bad", Media: "warn", Baja: "ok" };

const PAGE_SIZES = [12, 25, 50];
const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

export function AuditWorkspace({
  entries,
  products,
  agents,
  now,
}: {
  entries: AuditEntry[];
  products: Product[];
  agents: Agent[];
  now: number;
}) {
  const [tab, setTab] = useState<MainTab>("eventos");
  const [filters, setFilters] = useState<RowFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(12);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("resumen");

  const rows = useMemo(() => auditRows(entries, products, agents, now), [entries, products, agents, now]);
  const kpis = auditKpis(rows, now);
  const options = useMemo(() => filterOptions(rows), [rows]);
  const filtered = useMemo(() => filterRows(rows, filters, now), [rows, filters, now]);
  const pageData = paginate(filtered, page, pageSize);
  const selected = rows.find((row) => row.id === selectedId) ?? pageData.items[0] ?? rows[0];
  const trace = selected ? correlationTrace(rows, selected.correlationId) : [];
  const realCount = rows.filter((row) => !row.isDemo).length;

  function update(patch: Partial<RowFilters>) {
    setFilters((current) => ({ ...current, ...patch }));
    setPage(0);
  }

  function exportCsv() {
    const csv = toCsv(
      ["Evento", "Fecha", "Tipo", "Acción", "Actor", "Proyecto", "Resultado", "Criticidad", "Correlación", "Origen"],
      filtered
        .slice(0, 2000)
        .map((row) => [
          row.code,
          new Date(row.at).toISOString(),
          row.type,
          row.title,
          row.actor,
          row.projectCode ?? "",
          row.result,
          row.criticality,
          row.correlationId,
          row.isDemo ? "demostración" : "backend",
        ]),
    );
    downloadCsv("auditoria.csv", csv);
  }

  if (rows.length === 0) {
    return (
      <div>
        <PageHeader title={AUDIT_TITLE} description={AUDIT_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState icon={FileText} title="El registro está vacío" description="Todavía no hay eventos de auditoría." />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={AUDIT_TITLE}
        description={AUDIT_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <Button variant="outline" onClick={exportCsv}>
              <Download /> Exportar
            </Button>
            <Button disabled title={`Pendiente: el backend no genera paquetes de auditoría (${EXPORT_FORMATS.join(", ")})`}>
              <ShieldCheck /> Generar paquete de auditoría
            </Button>
          </>
        }
      />

      {/* KPIs */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6" aria-label="Indicadores de auditoría">
        <KpiCard label="Eventos hoy" leading={<FileText className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.today)} />
        <KpiCard
          label="Acciones críticas"
          leading={<AlertTriangle className={cn("size-7 shrink-0", kpis.critical > 0 ? "text-destructive" : "text-primary")} />}
          value={formatInteger(kpis.critical)}
          tone={kpis.critical > 0 ? "danger" : "default"}
        />
        <KpiCard label="Aprobaciones" leading={<CircleCheck className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.approvals)} />
        <KpiCard label="Cambios de configuración" leading={<Settings2 className="size-7 shrink-0 text-primary" />} value={formatInteger(kpis.configChanges)} />
        <KpiCard
          label="Errores"
          leading={<XCircle className={cn("size-7 shrink-0", kpis.errors > 0 ? "text-warning" : "text-primary")} />}
          value={formatInteger(kpis.errors)}
          tone={kpis.errors > 0 ? "warning" : "default"}
        />
        <KpiCard
          label="Evidencias completas"
          leading={<ShieldCheck className="size-7 shrink-0 text-primary" />}
          value={formatPercent(kpis.evidenceRate)}
          caption="Dato de demostración"
        />
      </section>

      <Tabs value={tab} onValueChange={(value) => setTab(value as MainTab)}>
        <TabsList className="flex flex-wrap justify-start group-data-horizontal/tabs:h-auto">
          {MAIN_TABS.map((item) => (
            <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={filters.window} onChange={(e) => update({ window: e.target.value as AuditWindow })} aria-label="Periodo" className={INPUT_CLASS}>
          {Object.entries(WINDOW_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select value={filters.type} onChange={(e) => update({ type: e.target.value })} aria-label="Tipo" className={INPUT_CLASS}>
          <option value="all">Todos los tipos</option>
          {options.types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <select value={filters.actor} onChange={(e) => update({ actor: e.target.value })} aria-label="Actor" className={INPUT_CLASS}>
          <option value="all">Todos los actores</option>
          {options.actors.map((actor) => (
            <option key={actor} value={actor}>
              {actor}
            </option>
          ))}
        </select>
        <select value={filters.project} onChange={(e) => update({ project: e.target.value })} aria-label="Proyecto" className={INPUT_CLASS}>
          <option value="all">Todos los proyectos</option>
          {options.projects.map((project) => (
            <option key={project} value={project}>
              {project}
            </option>
          ))}
        </select>
        <select value={filters.criticality} onChange={(e) => update({ criticality: e.target.value })} aria-label="Criticidad" className={INPUT_CLASS}>
          <option value="all">Todas las criticidades</option>
          {["Alta", "Media", "Baja"].map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        <input
          value={filters.query}
          onChange={(e) => update({ query: e.target.value })}
          type="search"
          placeholder="Buscar eventos, ID, texto…"
          aria-label="Buscar en el registro"
          className={cn(INPUT_CLASS, "min-w-48 flex-1")}
        />
      </div>

      {tab === "eventos" ? (
        <div className="grid gap-4 min-[106.25rem]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          {/* Tabla */}
          <div className="min-w-0 space-y-3">
            <Card className="min-w-0">
              <CardContent className="space-y-3">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="text-muted-foreground">
                      <tr>
                        <th className="pb-2 text-left font-normal">Fecha y hora</th>
                        <th className="pb-2 text-left font-normal">Tipo</th>
                        <th className="pb-2 text-left font-normal">Acción / Evento</th>
                        <th className="pb-2 text-left font-normal">Actor</th>
                        <th className="pb-2 text-left font-normal">Proyecto</th>
                        <th className="pb-2 text-left font-normal">Resultado</th>
                        <th className="pb-2 text-left font-normal">Criticidad</th>
                        <th className="pb-2 text-left font-normal">Correlación</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageData.items.map((row) => (
                        <tr
                          key={row.id}
                          onClick={() => {
                            setSelectedId(row.id);
                            setDetailTab("resumen");
                          }}
                          aria-selected={selected?.id === row.id}
                          className={cn("cursor-pointer border-t transition hover:bg-panel-hover", selected?.id === row.id && "bg-primary/5")}
                        >
                          <td className="py-1.5 whitespace-nowrap text-muted-foreground">{formatDateTime(row.at)}</td>
                          <td className="py-1.5">{row.type}</td>
                          <td className="py-1.5">
                            <span className="block leading-tight font-medium">{row.title}</span>
                            <span className="block text-muted-foreground">{row.detail}</span>
                          </td>
                          <td className="py-1.5 break-words">{row.actor}</td>
                          <td className="py-1.5 whitespace-nowrap">{row.projectCode ?? "—"}</td>
                          <td className="py-1.5">
                            <LevelChip tone={RESULT_TONE[row.result]}>{row.result}</LevelChip>
                          </td>
                          <td className="py-1.5">
                            <LevelChip tone={CRITICALITY_TONE[row.criticality]}>{row.criticality}</LevelChip>
                          </td>
                          <td className="py-1.5 font-mono whitespace-nowrap text-muted-foreground">{row.correlationId}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {pageData.total === 0 ? <p className="py-3 text-sm text-muted-foreground">Sin eventos con estos filtros.</p> : null}

                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    Mostrando {formatInteger(pageData.from)}–{formatInteger(pageData.to)} de {formatInteger(pageData.total)} eventos
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Button size="xs" variant="outline" disabled={pageData.page === 0} onClick={() => setPage(pageData.page - 1)}>
                      Anterior
                    </Button>
                    <span className="tabular-nums">
                      {pageData.page + 1} / {pageData.pages}
                    </span>
                    <Button size="xs" variant="outline" disabled={pageData.page >= pageData.pages - 1} onClick={() => setPage(pageData.page + 1)}>
                      Siguiente
                    </Button>
                    <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(0); }} aria-label="Eventos por página" className={INPUT_CLASS}>
                      {PAGE_SIZES.map((size) => (
                        <option key={size} value={size}>
                          {size} por página
                        </option>
                      ))}
                    </select>
                  </span>
                </div>
              </CardContent>
            </Card>

            <AnomaliesCard anomalies={anomalies(rows, now)} />
          </div>

          {/* Detalle */}
          <div className="min-w-0 space-y-4">
            {selected ? (
              <>
                <Card className="min-w-0">
                  <CardContent className="space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          {selected.code}
                          <LevelChip tone={selected.isDemo ? "neutral" : "ok"}>{selected.isDemo ? "Evento de demostración" : "Evento verificado"}</LevelChip>
                        </p>
                        <p className="flex flex-wrap items-center gap-2 text-xl leading-tight font-semibold">
                          {selected.title}
                          <LevelChip tone={CRITICALITY_TONE[selected.criticality]}>{selected.criticality} criticidad</LevelChip>
                        </p>
                        <p className="text-xs text-muted-foreground">{formatDateTime(selected.at)}</p>
                      </div>
                    </div>
                    <Tabs value={detailTab} onValueChange={(value) => setDetailTab(value as DetailTab)}>
                      <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                        {DETAIL_TABS.map((item) => (
                          <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                            {item.label}
                          </TabsTrigger>
                        ))}
                      </TabsList>
                    </Tabs>
                  </CardContent>
                </Card>

                {detailTab === "resumen" ? (
                  <>
                    <EventFieldsCard row={selected} />
                    <ChangesCard row={selected} />
                    <div className="grid gap-4 sm:grid-cols-2">
                      <ProjectContextCard row={selected} />
                      <IntegrityCard row={selected} />
                    </div>
                  </>
                ) : null}
                {detailTab === "datos" ? (
                  <>
                    <EventFieldsCard row={selected} />
                    <ChangesCard row={selected} />
                  </>
                ) : null}
                {detailTab === "evidencias" ? (
                  <>
                    <EvidencesCard row={selected} />
                    <IntegrityCard row={selected} />
                  </>
                ) : null}
                {detailTab === "trazabilidad" ? (
                  <>
                    <TraceCard steps={trace} />
                    <ProjectContextCard row={selected} />
                  </>
                ) : null}
                {detailTab === "json" ? <JsonCard row={selected} /> : null}
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {tab === "timeline" ? <TimelineCard rows={filtered} /> : null}
      {tab === "proyectos" ? <ProjectsTabCard rows={filtered} /> : null}
      {tab === "agentes" ? <ActorsTabCard rows={filtered} /> : null}
      {tab === "seguridad" ? <SecurityTabCard rows={filtered} /> : null}
      {tab === "integridad" ? <IntegrityTabCard rows={filtered} evidenceRate={kpis.evidenceRate} /> : null}
      {tab === "retencion" ? <RetentionTabCard /> : null}

      <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <Package className="size-3.5" />
        {formatInteger(realCount)} eventos reales del registro del backend · {formatInteger(rows.length - realCount)} de demostración para llenar la
        ventana de 30 días.
      </p>
    </div>
  );
}
