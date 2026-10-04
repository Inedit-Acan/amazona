"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Ban, CircleDot, Clock, FolderKanban, PackageSearch, PauseCircle, Plus } from "lucide-react";
import type { Agent } from "@/lib/api";
import { formatInteger, formatPercent } from "@/lib/format";
import {
  NO_DATA,
  PORTFOLIO_TABS,
  UNREAD,
  PROJECT_STATUS_LABEL,
  filterProjects,
  formatPlanAmount,
  nextStep,
  portfolioCounts,
  projectCard,
  statusDistribution,
  type PortfolioTab,
  type ProjectCard,
  type ProjectSource,
} from "@/lib/projects-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DonutChart } from "@/components/donut-chart";
import { EmptyState } from "@/components/empty-state";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { RingGauge } from "@/components/ring-gauge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { PROJECTS_DESCRIPTION, PROJECTS_TITLE } from "./copy";
import {
  ActivityCard,
  AgentsCard,
  DecisionCard,
  MilestonesCard,
  NextStepCard,
  NotCalculatedCard,
  PipelineStepper,
  PlanCard,
  RisksCard,
  StagesCard,
  formatDayOrNoData,
} from "./projects-panels";

// La cartera de Proyectos (M45, Commit 11): sólo proyectos del backend, y ni una cifra sin fuente.
//
// Lo que esta pantalla ya NO hace: convertir productos en proyectos, generar pedidos con `buildOrders()` para calcular
// un «beneficio real», completar la lista con proyectos de `lib/demo/projects.ts`, inventar mercado y categoría, y
// comparar lo previsto con un «real» que salía de ruido determinista. Si no hay proyectos, se dice.

const DETAIL_TABS = [
  { key: "resumen", label: "Resumen" },
  { key: "etapas", label: "Etapas" },
  { key: "hitos", label: "Hitos" },
  { key: "proyeccion", label: "Proyección" },
  { key: "actividad", label: "Actividad" },
] as const;

type DetailTab = (typeof DETAIL_TABS)[number]["key"];

const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

const TONE_CLASS: Record<LevelTone, string> = {
  ok: "text-primary",
  warn: "text-warning",
  bad: "text-destructive",
  neutral: "text-muted-foreground",
};

/** Guarda la selección en la URL sin recargar el servidor. */
function syncUrl(id: string) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("proyecto", id);
  window.history.replaceState(null, "", url);
}

export function ProjectsWorkspace({
  sources,
  agents,
  agentsUnread,
  initialSelection,
}: {
  sources: ProjectSource[];
  agents: Agent[];
  agentsUnread: boolean;
  initialSelection?: string;
}) {
  const [tab, setTab] = useState<PortfolioTab>("all");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [detailTab, setDetailTab] = useState<DetailTab>("resumen");
  const [selectedId, setSelectedId] = useState<string | null>(initialSelection ?? null);

  const projects = useMemo<ProjectCard[]>(() => sources.map((source) => projectCard(source)), [sources]);

  if (projects.length === 0) {
    return (
      <div className="space-y-5">
        <PageHeader title={PROJECTS_TITLE} description={PROJECTS_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="El backend no tiene ningún proyecto"
              description={
                "Un proyecto lo crea el Director ejecutivo al validar un objetivo. No hay ninguno, así que esta pantalla " +
                "no enseña nada: un producto del catálogo no es un proyecto, y rellenarla con productos o con ejemplos " +
                "haría parecer que hay actividad empresarial donde no la hay."
              }
              action={
                <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/ceo" />}>
                  Crear un objetivo en Director ejecutivo
                </Button>
              }
            />
          </CardContent>
        </Card>
        <NotCalculatedCard />
      </div>
    );
  }

  const counts = portfolioCounts(projects);
  const visible = filterProjects(projects, { tab, query, status });
  const selected = projects.find((project) => project.id === selectedId) ?? visible[0] ?? projects[0];
  const step = nextStep(selected);
  const distribution = statusDistribution(projects);

  function selectProject(id: string) {
    setSelectedId(id);
    setDetailTab("resumen");
    syncUrl(id);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={PROJECTS_TITLE}
        description={PROJECTS_DESCRIPTION}
        actions={
          <Button nativeButton={false} render={<Link href="/ceo" />}>
            <Plus /> Nuevo objetivo / proyecto
          </Button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.25fr)]">
        {/* Cartera */}
        <div className="min-w-0 space-y-4">
          <section className="grid grid-cols-2 gap-2.5 sm:grid-cols-4" aria-label="Resumen de la cartera">
            {[
              { key: "total", label: "Proyectos", value: counts.total, icon: FolderKanban, tone: "neutral" as LevelTone },
              { key: "validation", label: "En validación", value: counts.validation, icon: CircleDot, tone: "warn" as LevelTone },
              { key: "execution", label: "En ejecución", value: counts.execution, icon: Clock, tone: "ok" as LevelTone },
              { key: "paused", label: "Pausados", value: counts.paused, icon: PauseCircle, tone: "neutral" as LevelTone },
              { key: "closed", label: "Cerrados", value: counts.closed, icon: Ban, tone: "neutral" as LevelTone },
              { key: "plan", label: "Con proyección", value: counts.withPlan, icon: CircleDot, tone: "warn" as LevelTone },
            ].map((item) => (
              <Card key={item.key} className="min-w-0 gap-0 py-3">
                <CardContent className="flex items-center gap-2.5 px-3">
                  <item.icon className={cn("size-5 shrink-0", TONE_CLASS[item.tone])} />
                  <span className="min-w-0">
                    <span className="block text-lg leading-tight font-semibold">{formatInteger(item.value)}</span>
                    <span className="block text-[11px] leading-tight text-muted-foreground">{item.label}</span>
                  </span>
                </CardContent>
              </Card>
            ))}
          </section>

          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Cartera</CardTitle>
              <CardAction className="flex gap-1.5">
                <DataProvenanceBadge
                  status="verified"
                  compact
                  tooltip="Estado, tareas e inicio salen del backend y de su registro de auditoría. No cubre la columna de proyección."
                />
                <DataProvenanceBadge
                  status="planned"
                  compact
                  tooltip="Solo la columna «Proyección (PLAN)»: lo que el modelo espera si los supuestos del objetivo se cumplen. No ha ocurrido."
                />
              </CardAction>
            </CardHeader>
            <CardContent className="space-y-3">
              <Tabs value={tab} onValueChange={(value) => setTab(value as PortfolioTab)}>
                <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                  {PORTFOLIO_TABS.map((item) => (
                    <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                      {item.label} ({filterProjects(projects, { tab: item.key }).length})
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>

              <div className="flex flex-wrap gap-2">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  type="search"
                  placeholder="Buscar proyecto…"
                  aria-label="Buscar proyecto"
                  className={cn(INPUT_CLASS, "flex-1")}
                />
                <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Estado" className={INPUT_CLASS}>
                  <option value="all">Estado</option>
                  {Object.entries(PROJECT_STATUS_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="pb-2 text-left font-normal">Proyecto</th>
                      <th className="pb-2 text-left font-normal">Estado</th>
                      <th className="pb-2 text-right font-normal">Tareas</th>
                      <th className="pb-2 text-right font-normal">Proyección (PLAN)</th>
                      <th className="pb-2 text-right font-normal">Inicio registrado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((project) => (
                      <tr
                        key={project.id}
                        onClick={() => selectProject(project.id)}
                        aria-selected={project.id === selected.id}
                        className={cn("cursor-pointer border-t transition hover:bg-panel-hover", project.id === selected.id && "bg-primary/5")}
                      >
                        <td className="py-1.5">
                          <span className="block leading-tight font-medium">{project.name}</span>
                          <span className="block font-mono text-[10px] leading-tight text-muted-foreground">{project.id}</span>
                        </td>
                        <td className="py-1.5">
                          <LevelChip tone={project.statusTone}>{project.statusLabel}</LevelChip>
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {project.unread.includes("tasks")
                            ? UNREAD
                            : project.progress.total === 0
                              ? NO_DATA
                              : `${project.progress.done}/${project.progress.total}`}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {project.plannedMonthlyProfit === null
                            ? project.planAbsence === "decision_unread"
                              ? UNREAD
                              : NO_DATA
                            : formatPlanAmount(project.plannedMonthlyProfit.value)}
                        </td>
                        <td className="py-1.5 text-right whitespace-nowrap text-muted-foreground">{project.unread.includes("audit") ? UNREAD : formatDayOrNoData(project.startedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visible.length === 0 ? <p className="py-3 text-sm text-muted-foreground">Sin proyectos con estos filtros.</p> : null}
              </div>
            </CardContent>
          </Card>

          <Card className="min-w-0">
            <CardHeader>
              <CardTitle>Proyectos por estado</CardTitle>
              <CardAction>
                <DataProvenanceBadge status="verified" compact tooltip="Reparto de los estados que guarda el backend." />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-4">
              <DonutChart
                ariaLabel="Proyectos por estado"
                segments={distribution.map((item) => ({ key: item.key, value: item.value, color: item.color }))}
                centerLabel={formatInteger(counts.total)}
                centerCaption="Total"
                size={116}
              />
              <ul className="min-w-28 flex-1 space-y-1.5 text-xs">
                {distribution.map((item) => (
                  <li key={item.key} className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="size-2.5 shrink-0 rounded-full" style={{ background: item.color }} aria-hidden />
                      {item.label}
                    </span>
                    <span className="tabular-nums">{item.value}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <NotCalculatedCard />
        </div>

        {/* Detalle */}
        <div className="min-w-0 space-y-4">
          <Card className="min-w-0">
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-xs text-muted-foreground">{selected.id}</p>
                  <p className="text-xl leading-tight font-semibold">{selected.name}</p>
                </div>
                <LevelChip tone={selected.statusTone}>{selected.statusLabel}</LevelChip>
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

              <section className="grid grid-cols-2 gap-2.5 lg:grid-cols-4" aria-label="Indicadores del proyecto">
                <div className="flex min-w-0 items-center gap-2 rounded-xl border bg-background/40 p-2.5">
                  <RingGauge
                    value={selected.progress.ratio}
                    size={52}
                    centerLabel={selected.unread.includes("tasks") || selected.progress.total === 0 ? "—" : formatPercent(selected.progress.ratio, 0)}
                  />
                  <span className="min-w-0">
                    <span className="block text-[11px] leading-tight text-muted-foreground">Tareas completadas</span>
                    <span className="block text-sm font-semibold">
                      {selected.unread.includes("tasks")
                        ? UNREAD
                        : selected.progress.total === 0
                          ? NO_DATA
                          : `${selected.progress.done}/${selected.progress.total}`}
                    </span>
                  </span>
                </div>
                {[
                  { label: "Estado del backend", value: selected.statusLabel },
                  {
                    label: "Inicio registrado",
                    value: selected.unread.includes("audit") ? UNREAD : formatDayOrNoData(selected.startedAt),
                  },
                  {
                    label: "Decisión",
                    value: selected.decisionLabel ?? (selected.unread.includes("decision") ? UNREAD : NO_DATA),
                  },
                ].map((item) => (
                  <div key={item.label} className="flex min-w-0 flex-col justify-center rounded-xl border bg-background/40 p-2.5">
                    <span className="block text-[11px] leading-tight text-muted-foreground">{item.label}</span>
                    <span className="block text-[13px] leading-tight font-semibold break-words">{item.value}</span>
                  </div>
                ))}
              </section>

              <PipelineStepper stages={selected.stages} />
            </CardContent>
          </Card>

          {detailTab === "resumen" ? (
            <>
              <div className="grid gap-4 min-[106.25rem]:grid-cols-2">
                <NextStepCard step={step} />
                <DecisionCard project={selected} />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <RisksCard risks={selected.risks} unread={selected.unread.includes("decision")} />
                <AgentsCard agents={agents} unread={agentsUnread} />
              </div>
              <PlanCard project={selected} />
            </>
          ) : null}

          {detailTab === "etapas" ? <StagesCard stages={selected.stages} /> : null}

          {detailTab === "hitos" ? <MilestonesCard milestones={selected.milestones} unread={selected.unread.includes("audit") || selected.unread.includes("tasks")} /> : null}

          {detailTab === "proyeccion" ? <PlanCard project={selected} /> : null}

          {detailTab === "actividad" ? (
            <ActivityCard entries={sources.find((source) => source.project.id === selected.id)?.audit ?? []} limit={20} unread={selected.unread.includes("audit")} />
          ) : null}
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground">
        {formatInteger(projects.length)} proyectos del backend. Esta pantalla no convierte productos, oportunidades ni
        señales en proyectos, y no contiene ningún dato de demostración.
      </p>
    </div>
  );
}
