"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Ban, CalendarClock, FolderKanban, Gauge, Rocket, ShieldAlert, TrendingUp, Workflow } from "lucide-react";
import type { Decision, Project, Task } from "@/lib/api";
import { deriveHealthDimensions, overallRisk } from "@/lib/decision-health";
import { formatAmount, formatInteger } from "@/lib/format";
import { GROUP_LABELS, countByGroup, projectGroup, projectedFinance, taskProgress, type ProjectGroup } from "@/lib/projects";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { KpiCard } from "@/components/kpi-card";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { ProjectHealth } from "@/components/project-health";
import { StackedBar } from "@/components/stacked-bar";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const PENDING_PORTFOLIO: PendingFeature[] = [
  {
    icon: TrendingUp,
    title: "Beneficio real y por mercado",
    description: "Un proyecto no está enlazado a producto, mercado ni ventas: solo se ve el beneficio previsto que calculó el CEO.",
  },
  {
    icon: Rocket,
    title: "Fases de lanzamiento y operación",
    description: "Preparación, lanzamiento, operativo y escala; hoy el CEO solo valida (validación → aprobado / rechazado).",
  },
  {
    icon: Workflow,
    title: "Vistas Pipeline y Timeline",
    description: "El portfolio como tablero por fase y como línea de tiempo.",
  },
  {
    icon: CalendarClock,
    title: "Fecha de inicio y producto",
    description: "El proyecto no guarda su fecha de creación ni el producto al que se refiere.",
  },
];

export interface PortfolioProject {
  project: Project;
  decision: Decision | null;
  tasks: Task[];
}

const GROUP_ORDER: ProjectGroup[] = ["validation", "active", "rejected", "other"];

export function ProjectsPortfolio({ items }: { items: PortfolioProject[] }) {
  const router = useRouter();
  const [filter, setFilter] = useState<ProjectGroup | "all">("all");

  const counts = useMemo(() => countByGroup(items.map((i) => i.project)), [items]);
  const atRisk = useMemo(
    () => items.filter((i) => overallRisk(deriveHealthDimensions(i.decision)) === "high").length,
    [items],
  );
  // Solo cuentan los proyectos que siguen vivos: uno rechazado ya no va a dar beneficio.
  const expectedProfit = useMemo(() => {
    const live = items.filter((i) => projectGroup(i.project.status) !== "rejected");
    const values = live.flatMap((i) => {
      const finance = projectedFinance(i.decision);
      return finance ? [finance.monthlyProfit] : [];
    });
    return values.length > 0 ? values.reduce((a, b) => a + b, 0) : null;
  }, [items]);
  const visible = useMemo(
    () => (filter === "all" ? items : items.filter((i) => projectGroup(i.project.status) === filter)),
    [items, filter],
  );

  const columns: DataTableColumn<PortfolioProject>[] = [
    {
      key: "project",
      header: "Proyecto",
      cell: (row) => (
        <div className="min-w-0">
          <p className="max-w-[22rem] truncate font-medium">{row.project.name}</p>
          <p className="font-mono text-[11px] text-muted-foreground">{row.project.id.slice(0, 8)}</p>
        </div>
      ),
      sortValue: (row) => row.project.name,
      exportValue: (row) => row.project.name,
    },
    { key: "status", header: "Estado", cell: (row) => <StatusChip status={row.project.status} />, sortValue: (row) => row.project.status },
    { key: "health", header: "Salud", cell: (row) => <ProjectHealth decision={row.decision} compact /> },
    {
      key: "score",
      header: "Score",
      cell: (row) =>
        row.decision?.opportunity_score != null ? (
          <span className="tabular-nums">{row.decision.opportunity_score.toFixed(2).replace(".", ",")}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      sortValue: (row) => row.decision?.opportunity_score ?? -1,
    },
    {
      key: "progress",
      header: "Progreso",
      cell: (row) => {
        const progress = taskProgress(row.tasks);
        return (
          <div className="flex min-w-28 items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${progress.done} de ${progress.total} tareas`}>
              <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(progress.ratio * 100)}%` }} />
            </div>
            <span className="text-xs tabular-nums text-muted-foreground">
              {progress.done}/{progress.total}
            </span>
          </div>
        );
      },
      sortValue: (row) => taskProgress(row.tasks).ratio,
    },
    {
      key: "profit",
      header: "Beneficio prev. (mes)",
      cell: (row) => {
        const finance = projectedFinance(row.decision);
        return finance ? (
          <span className={finance.monthlyProfit < 0 ? "tabular-nums text-destructive" : "tabular-nums"}>{formatAmount(finance.monthlyProfit)}</span>
        ) : (
          <DataProvenanceBadge status="pending" tooltip="Este proyecto no tiene una evidencia de finanzas con beneficio previsto." />
        );
      },
      sortValue: (row) => projectedFinance(row.decision)?.monthlyProfit ?? Number.NEGATIVE_INFINITY,
    },
  ];

  if (items.length === 0) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={FolderKanban}
            title="Todavía no hay proyectos"
            description="Cada validación de producto orquestada por el Director ejecutivo crea un proyecto."
            action={
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/ceo" />}>
                Ir al Director ejecutivo
              </Button>
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores del portfolio">
        <KpiCard label="Proyectos" value={formatInteger(items.length)} icon={FolderKanban} caption="Validaciones orquestadas por el CEO" />
        <KpiCard label="En validación" value={formatInteger(counts.validation)} icon={Gauge} caption="Borrador o validando" />
        <KpiCard label="Activos" value={formatInteger(counts.active)} icon={Rocket} caption="Aprobados, en ejecución o monitorizados" />
        <KpiCard label="Rechazados" value={formatInteger(counts.rejected)} icon={Ban} caption="Rechazados o fallidos" />
        <KpiCard
          label="En riesgo"
          value={formatInteger(atRisk)}
          icon={ShieldAlert}
          tone={atRisk > 0 ? "danger" : "default"}
          caption="Alguna validación en NO_GO"
        />
        <KpiCard
          label="Beneficio previsto (mes)"
          value={expectedProfit !== null ? formatAmount(expectedProfit) : "—"}
          icon={TrendingUp}
          caption="Proyectos vivos · el beneficio real está pendiente"
          provenance="estimated"
          provenanceTooltip="Suma del beneficio mensual que calculó el especialista de finanzas con los supuestos de cada objetivo. No son ventas reales."
        />
      </section>

      <div className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-9">
          <CardHeader>
            <CardTitle>Portfolio</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="verified" tooltip="Proyectos, tareas y decisiones guardados en la base de datos." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por estado">
              <Button type="button" size="sm" variant={filter === "all" ? "secondary" : "outline"} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
                Todos <span className="tabular-nums text-muted-foreground">{items.length}</span>
              </Button>
              {GROUP_ORDER.map((group) => (
                <Button
                  key={group}
                  type="button"
                  size="sm"
                  variant={filter === group ? "secondary" : "outline"}
                  aria-pressed={filter === group}
                  onClick={() => setFilter(group)}
                >
                  {GROUP_LABELS[group]} <span className="tabular-nums text-muted-foreground">{counts[group]}</span>
                </Button>
              ))}
            </div>
            <DataTable
              columns={columns}
              rows={visible}
              getRowId={(row) => row.project.id}
              onSelect={(row) => router.push(`/projects/${row.project.id}`)}
              getSearchText={(row) => `${row.project.name} ${row.project.id}`}
              searchPlaceholder="Buscar proyecto…"
              exportFileName="proyectos.csv"
              emptyMessage="Ningún proyecto coincide con el filtro."
            />
            <p className="text-[11px] text-muted-foreground">Pulsa una fila para abrir el expediente del proyecto.</p>
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Proyectos por estado</CardTitle>
          </CardHeader>
          <CardContent>
            <StackedBar
              ariaLabel="Proyectos por estado"
              segments={[
                { key: "validation", label: GROUP_LABELS.validation, value: counts.validation, valueLabel: String(counts.validation), className: "bg-amber-500" },
                { key: "active", label: GROUP_LABELS.active, value: counts.active, valueLabel: String(counts.active), className: "bg-primary" },
                { key: "rejected", label: GROUP_LABELS.rejected, value: counts.rejected, valueLabel: String(counts.rejected), className: "bg-red-500" },
                { key: "other", label: GROUP_LABELS.other, value: counts.other, valueLabel: String(counts.other), className: "bg-muted-foreground/50" },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <PendingFeatures
        title="Portfolio completo — pendiente de backend"
        tooltip="Requieren enlazar cada proyecto con su producto, mercado y resultados reales."
        items={PENDING_PORTFOLIO}
        columns={4}
        note="Hoy un proyecto es una validación del CEO: nombre, estado, tareas y decisión. No guarda producto, mercado, fechas ni resultados reales, así que no hay beneficio real ni por mercado, fases de lanzamiento ni fecha de inicio."
      />
    </div>
  );
}
