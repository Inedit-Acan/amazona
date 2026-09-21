import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleDot,
  Circle,
  FileText,
  Gauge,
  GraduationCap,
  LineChart,
  ListChecks,
  Percent,
  ShieldCheck,
  Target,
  TrendingUp,
  Wallet,
  X,
} from "lucide-react";
import { ApiError, api, type Approval, type AuditEntry, type Decision, type Project, type Task } from "@/lib/api";
import { deriveHealthDimensions, overallRisk } from "@/lib/decision-health";
import { formatAmount, formatInteger, formatPercent } from "@/lib/format";
import {
  DECISION_VERDICT,
  UNLINKED_STAGES,
  milestones,
  pipelineSteps,
  projectRisks,
  projectedFinance,
  taskCounts,
  taskProgress,
  type StageState,
} from "@/lib/projects";
import { ApiErrorAlert } from "@/components/api-error";
import { CorrelationTrace } from "@/components/correlation-trace";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { KpiCard, type KpiTone } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { PendingFeatures, type PendingFeature } from "@/components/pending-features";
import { ProjectHealth } from "@/components/project-health";
import { StatusChip } from "@/components/status-chip";
import { VerdictBanner } from "@/components/verdict-banner";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const PENDING_DETAIL: PendingFeature[] = [
  {
    icon: TrendingUp,
    title: "Beneficio real y capital comprometido",
    description: "El proyecto no está enlazado a un producto ni a ventas: solo hay el beneficio previsto por el CEO y el gasto solicitado.",
  },
  {
    icon: LineChart,
    title: "Previsto vs real",
    description: "Ventas, ingresos, CAC, margen, devoluciones y entrega comparados con lo previsto.",
  },
  {
    icon: GraduationCap,
    title: "Aprendizajes del proyecto",
    description: "Lo que salió mejor o peor que la previsión y que debe alimentar al sistema.",
  },
  {
    icon: FileText,
    title: "Métricas, finanzas y documentos",
    description: "Pestañas de métricas clave, finanzas y documentos del expediente.",
  },
];

const STAGE_KPI_TONE: Record<"low" | "medium" | "high", KpiTone> = { low: "success", medium: "warning", high: "danger" };
const RISK_TITLE = { low: "Riesgo bajo", medium: "Riesgo medio", high: "Riesgo alto" } as const;

const STAGE_STYLE: Record<StageState, string> = {
  done: "border-primary bg-primary text-primary-foreground",
  current: "border-primary text-primary shadow-[0_0_10px_-2px_var(--emerald)]",
  blocked: "border-red-500 bg-red-500/15 text-red-500",
  todo: "border-border text-muted-foreground",
};

function outputSummary(task: Task): string {
  if (task.status === "FAILED") return task.error ?? "Fallido";
  const output = task.output as { recommendation?: string; confidence?: number } | null;
  if (!output?.recommendation) return "—";
  return `${output.recommendation}${output.confidence != null ? ` (${Math.round(output.confidence * 100)}%)` : ""}`;
}

export default async function ProjectDetailPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;

  let project: Project;
  try {
    project = await api.getProject(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    return (
      <div>
        <PageHeader title="Proyecto" />
        <ApiErrorAlert message={err instanceof Error ? err.message : "Error desconocido"} />
      </div>
    );
  }

  const [tasks, decisions] = await Promise.all([
    api.listTasks(project.id).catch(() => [] as Task[]),
    api.listDecisionsForProject(project.id).catch(() => [] as Decision[]),
  ]);
  const decision = decisions[0] ?? null;
  const [audit, approvals] = await Promise.all([
    decision ? api.listAudit(decision.correlation_id).catch(() => [] as AuditEntry[]) : Promise.resolve([] as AuditEntry[]),
    decision ? api.listApprovals().catch(() => [] as Approval[]) : Promise.resolve([] as Approval[]),
  ]);
  const approval = decision ? approvals.find((a) => a.decision_id === decision.id) : undefined;

  const health = deriveHealthDimensions(decision);
  const risk = overallRisk(health);
  const progress = taskProgress(tasks);
  const counts = taskCounts(tasks);
  const steps = pipelineSteps(tasks, decision);
  const risks = projectRisks(decision);
  const finance = projectedFinance(decision);
  const verdict = decision ? DECISION_VERDICT[decision.status] : undefined;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/projects" className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Proyectos
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <PageHeader title={project.name} description={project.id} />
          <div className="flex items-center gap-2">
            <StatusChip status={project.status} />
            <Button size="sm" nativeButton={false} render={<Link href="/ceo" />}>
              Nuevo objetivo
            </Button>
          </div>
        </div>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Indicadores del proyecto">
        <KpiCard
          label="Project Health"
          value={RISK_TITLE[risk]}
          icon={ShieldCheck}
          tone={STAGE_KPI_TONE[risk]}
          caption="La peor de las cuatro validaciones"
          provenance="verified"
          provenanceTooltip="Se deriva de la recomendación real de cada especialista en la decisión del CEO."
        />
        <KpiCard
          label="Progreso"
          value={formatPercent(progress.ratio, 0)}
          icon={Percent}
          caption={`${progress.done} de ${progress.total} tareas completadas`}
          provenance="verified"
        />
        <KpiCard
          label="Score de oportunidad"
          value={decision?.opportunity_score != null ? decision.opportunity_score.toFixed(2).replace(".", ",") : "—"}
          icon={Gauge}
          caption="Decisión del director ejecutivo"
          provenance={decision ? "estimated" : "pending"}
          provenanceTooltip="Calculado por el motor de decisión sobre datos de simulación."
        />
        <KpiCard
          label="Confianza"
          value={decision?.confidence != null ? formatPercent(decision.confidence, 0) : "—"}
          icon={Target}
          caption="De la decisión"
          provenance={decision ? "estimated" : "pending"}
        />
        <KpiCard
          label="Beneficio previsto (mes)"
          value={finance ? formatAmount(finance.monthlyProfit) : "—"}
          icon={TrendingUp}
          caption={
            finance
              ? finance.margin !== null
                ? `Margen ${formatPercent(finance.margin, 0)} · beneficio real pendiente`
                : "Beneficio real pendiente"
              : "Sin evidencia de finanzas"
          }
          provenance={finance ? "estimated" : "pending"}
          provenanceTooltip={
            finance
              ? "Calculado por el especialista de finanzas con los supuestos del objetivo. No son ventas reales."
              : "La decisión no trae una evidencia de finanzas con beneficio."
          }
        />
        <KpiCard
          label="Capital expuesto"
          value={approval?.amount != null ? formatInteger(approval.amount) : "—"}
          icon={Wallet}
          caption={approval?.amount != null ? `Solicitado: ${approval.action.replace(/_/g, " ")}` : "Sin gasto solicitado"}
          provenance={approval?.amount != null ? "verified" : "pending"}
          provenanceTooltip={
            approval?.amount != null
              ? "Importe de la aprobación de gasto de la decisión."
              : "No hay una solicitud de gasto asociada a este proyecto."
          }
        />
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Pipeline del proyecto</CardTitle>
          <CardAction>
            <DataProvenanceBadge status="verified" tooltip="Estado de las tareas del grafo del proyecto." />
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-4">
          <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
            {steps.map((step) => (
              <li key={step.task}>
                <Link
                  href={step.href}
                  className="flex h-full flex-col items-center gap-2 rounded-lg border bg-background/50 p-3 text-center transition-colors hover:bg-muted/50"
                >
                  <span className={cn("flex size-8 items-center justify-center rounded-full border", STAGE_STYLE[step.state])}>
                    {step.state === "done" ? <Check className="size-4" /> : step.state === "blocked" ? <X className="size-4" /> : step.state === "current" ? <CircleDot className="size-4" /> : <Circle className="size-4" />}
                  </span>
                  <span className="text-sm font-medium">{step.label}</span>
                  {step.recommendation ? <StatusChip status={step.recommendation} /> : <span className="text-[11px] text-muted-foreground">Sin evidencia</span>}
                </Link>
              </li>
            ))}
            {UNLINKED_STAGES.map((label) => (
              <li key={label}>
                <div className="flex h-full flex-col items-center gap-2 rounded-lg border border-dashed p-3 text-center" title="Esta fase no cuelga del proyecto en el backend">
                  <span className={cn("flex size-8 items-center justify-center rounded-full border", STAGE_STYLE.todo)}>
                    <Circle className="size-4" />
                  </span>
                  <span className="text-sm font-medium text-muted-foreground">{label}</span>
                  <DataProvenanceBadge status="pending" tooltip="Tienda, marketing y operaciones se generan por producto y mercado, no por proyecto." />
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[11px] text-muted-foreground">
            Las cuatro primeras fases son las tareas que el CEO valida en cada proyecto y enlazan a su módulo. Tienda,
            Marketing, Operaciones y Escala se trabajan por producto y mercado, sin vínculo con el proyecto.
          </p>
        </CardContent>
      </Card>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Próxima decisión</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {decision && verdict ? (
              <>
                <VerdictBanner tone={verdict.tone} title={verdict.title} detail={verdict.detail} />
                {decision.rationale ? <p className="text-xs text-muted-foreground">{decision.rationale}</p> : null}
                {approval ? (
                  <dl className="divide-y rounded-lg border px-3 text-sm">
                    <div className="flex justify-between gap-3 py-1.5">
                      <dt className="text-muted-foreground">Solicitud</dt>
                      <dd className="font-medium">{approval.action.replace(/_/g, " ")}</dd>
                    </div>
                    <div className="flex justify-between gap-3 py-1.5">
                      <dt className="text-muted-foreground">Importe</dt>
                      <dd className="font-medium tabular-nums">{approval.amount != null ? formatInteger(approval.amount) : "—"}</dd>
                    </div>
                    <div className="flex items-center justify-between gap-3 py-1.5">
                      <dt className="text-muted-foreground">Estado</dt>
                      <dd>
                        <StatusChip status={approval.status} />
                      </dd>
                    </div>
                  </dl>
                ) : null}
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" nativeButton={false} render={<Link href="/approvals" />}>
                    Abrir Aprobaciones
                    <ArrowRight />
                  </Button>
                  <Button size="sm" variant="outline" nativeButton={false} render={<Link href={`/audit?correlation_id=${decision.correlation_id}`} />}>
                    Ver trazabilidad
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Este proyecto todavía no tiene una decisión del director ejecutivo.</p>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Salud y riesgos</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="verified" tooltip="Recomendación real de cada especialista en la evidencia de la decisión." />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-4">
            <ProjectHealth decision={decision} />
            {risks.length > 0 ? (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">Riesgos señalados por los especialistas</p>
                <ul className="divide-y rounded-lg border text-sm">
                  {risks.map((item) => (
                    <li key={`${item.stage}-${item.risk}`} className="flex items-start justify-between gap-3 px-3 py-2">
                      <span className="text-destructive">{item.risk}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{item.stage}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-[11px] text-muted-foreground">Textos de los agentes (en inglés).</p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Los especialistas no han señalado riesgos.</p>
            )}
            <p className="text-[11px] text-muted-foreground">
              Canal, marketing, operaciones y el score numérico de salud: pendientes, no hay evidencias de esas
              dimensiones por proyecto.
            </p>
          </CardContent>
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Actividad reciente</CardTitle>
            <CardAction>
              <DataProvenanceBadge status="verified" tooltip="Eventos de auditoría de la decisión de este proyecto." />
            </CardAction>
          </CardHeader>
          <CardContent>
            {audit.length > 0 ? (
              <CorrelationTrace entries={audit} />
            ) : (
              <p className="text-sm text-muted-foreground">No hay eventos de auditoría para este proyecto.</p>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-6">
          <CardHeader>
            <CardTitle>Hitos y tareas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ul className="space-y-1.5">
              {milestones(tasks).map((milestone) => (
                <li key={milestone.label} className="flex items-center gap-2 text-sm">
                  <span
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded-full border",
                      milestone.done ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground",
                    )}
                  >
                    {milestone.done ? <Check className="size-2.5" /> : null}
                  </span>
                  <span className={cn(!milestone.done && "text-muted-foreground")}>{milestone.label}</span>
                </li>
              ))}
              {["Primera venta", "Primeras 100 ventas", "Break-even real"].map((label) => (
                <li key={label} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="size-4 shrink-0 rounded-full border border-dashed" />
                  <span className="flex-1">{label}</span>
                  <DataProvenanceBadge status="pending" tooltip="No hay ventas reales enlazadas al proyecto." />
                </li>
              ))}
            </ul>
            <dl className="grid grid-cols-4 gap-2 border-t pt-3 text-center text-xs">
              <div>
                <dt className="text-muted-foreground">Ejecutando</dt>
                <dd className="mt-0.5 text-sm font-medium tabular-nums">{counts.running}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">En espera</dt>
                <dd className="mt-0.5 text-sm font-medium tabular-nums">{counts.waiting}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Pendientes</dt>
                <dd className="mt-0.5 text-sm font-medium tabular-nums">{counts.pending}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Completadas</dt>
                <dd className="mt-0.5 text-sm font-medium tabular-nums">{counts.completed}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="size-4 text-primary" /> Grafo de tareas
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tarea</TableHead>
                <TableHead>Capacidad</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Resultado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TableRow key={task.id}>
                  <TableCell className="font-medium">{task.name.replace(/_/g, " ")}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{task.capability}</TableCell>
                  <TableCell>
                    <StatusChip status={task.status} />
                  </TableCell>
                  <TableCell className="text-sm">{outputSummary(task)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {decision && decision.evidence.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Evidencia de la decisión</CardTitle>
            <CardAction>
              <StatusChip status={decision.status} />
            </CardAction>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2 md:grid-cols-2">
              {decision.evidence.map((e, i) => (
                <li key={i} className="rounded-md border bg-muted/30 p-3 text-sm">
                  <p className="font-medium capitalize">{e.source.replace(/_/g, " ")}</p>
                  <p className="text-muted-foreground">{e.summary}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <PendingFeatures
        title="Expediente completo — pendiente de backend"
        tooltip="Requieren enlazar el proyecto con producto, mercado, ventas y aprendizajes que el backend aún no guarda."
        items={PENDING_DETAIL}
        columns={4}
        note="Un proyecto guarda su nombre, estado, tareas y decisión. Sin producto ni ventas enlazados no hay beneficio real, previsto vs real ni aprendizajes."
      />
    </div>
  );
}
