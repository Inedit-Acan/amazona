"use client";

import Link from "next/link";
import {
  ArrowRight,
  Ban,
  Bot,
  Check,
  CircleDot,
  Clock,
  FileText,
  GraduationCap,
  Lightbulb,
  ShieldAlert,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { Agent, AuditEntry } from "@/lib/api";
import { DEMO_DECISION_MINUTES, DEMO_DOCUMENTS } from "@/lib/demo/projects";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import type {
  ComparisonRow,
  Learning,
  NextDecision,
  ProjectCard,
  ProjectMilestone,
  ProjectPhase,
  ProjectRiskRow,
} from "@/lib/projects-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function formatDay(ts: number): string {
  return new Date(ts).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

const PHASE_ICON: Record<ProjectPhase["state"], LucideIcon> = {
  done: Check,
  current: CircleDot,
  blocked: Ban,
  todo: Clock,
};

// --- Pipeline ---------------------------------------------------------------------

export function PipelineStepper({ phases }: { phases: ProjectPhase[] }) {
  return (
    <ol className="grid grid-cols-4 gap-2 min-[106.25rem]:grid-cols-8">
      {phases.map((phase) => {
        const Icon = PHASE_ICON[phase.state];
        return (
          <li key={phase.key} className="min-w-0">
            <Link
              href={phase.href}
              className={cn(
                "flex min-w-0 flex-col items-center gap-1 rounded-xl border p-2 text-center transition hover:border-primary/50",
                phase.state === "done" && "border-primary/40 bg-primary/5",
                phase.state === "current" && "border-primary bg-primary/10",
                phase.state === "blocked" && "border-destructive/40 bg-destructive/5",
              )}
            >
              <span
                className={cn(
                  "flex size-7 items-center justify-center rounded-full border",
                  phase.state === "done" && "border-primary/50 bg-primary/20 text-primary",
                  phase.state === "current" && "border-primary bg-primary text-background",
                  phase.state === "blocked" && "border-destructive/50 bg-destructive/20 text-destructive",
                  phase.state === "todo" && "text-muted-foreground",
                )}
              >
                <Icon className="size-4" />
              </span>
              <span className="text-[11px] leading-tight font-medium">{phase.label}</span>
              <span
                className={cn(
                  "text-[11px] leading-tight",
                  phase.state === "blocked" ? "text-destructive" : phase.state === "current" ? "text-primary" : "text-muted-foreground",
                )}
              >
                {phase.detail}
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

// --- Próxima decisión --------------------------------------------------------------

const GATE_TONE: Record<NextDecision["gates"][number]["state"], LevelTone> = { ok: "ok", warn: "warn", bad: "bad" };

export function NextDecisionCard({ decision }: { decision: NextDecision }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Próxima decisión</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="estimated" compact tooltip="La decisión sale de la fase en la que está el proyecto y de las puertas de Legal, Economía y Tienda." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/40 bg-primary/10 text-primary">
            <Sparkles className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-base leading-tight font-semibold">{decision.title}</p>
            <p className="text-xs text-muted-foreground">Fase: {decision.phaseLabel}</p>
          </div>
        </div>
        <dl className="space-y-1.5 text-sm">
          {decision.amount !== null ? (
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Presupuesto solicitado</dt>
              <dd className="tabular-nums">{formatEuro(decision.amount, 0)}</dd>
            </div>
          ) : null}
          {decision.maxCac !== null ? (
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">CAC máximo</dt>
              <dd className="tabular-nums">{formatEuro(decision.maxCac)}</dd>
            </div>
          ) : null}
          {decision.gates.map((gate) => (
            <div key={gate.label} className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">{gate.label}</dt>
              <dd>
                <LevelChip tone={GATE_TONE[gate.state]}>{gate.detail}</LevelChip>
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-[11px] text-muted-foreground">Pendiente desde hace {DEMO_DECISION_MINUTES} minutos.</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href={decision.href} />}>
            Ver análisis <ArrowRight />
          </Button>
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/approvals" />}>
            Gestionar en Aprobaciones
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Aprobar o rechazar desde aquí necesita backend: la decisión se toma en Aprobaciones.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Métricas clave ----------------------------------------------------------------

export interface KeyMetric {
  key: string;
  label: string;
  value: string;
  detail: string;
  tone: "ok" | "warn" | "muted";
  href: string;
}

export function KeyMetricsCard({ metrics }: { metrics: KeyMetric[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Métricas clave del proyecto</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
        {metrics.map((metric) => (
          <Link key={metric.key} href={metric.href} className="min-w-0 rounded-xl border bg-background/40 p-2.5 transition hover:border-primary/50">
            <p className="text-[11px] leading-tight text-muted-foreground">{metric.label}</p>
            <p className={cn("mt-1 text-base leading-tight font-semibold", metric.tone === "ok" && "text-primary", metric.tone === "warn" && "text-warning")}>
              {metric.value}
            </p>
            <p className="mt-0.5 text-[11px] leading-tight text-muted-foreground">{metric.detail}</p>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

// --- Agentes y riesgos --------------------------------------------------------------

const AGENT_STATUS: Record<string, { label: string; tone: LevelTone }> = {
  AVAILABLE: { label: "Disponible", tone: "ok" },
  BUSY: { label: "Ejecutando", tone: "warn" },
  OFFLINE: { label: "Fuera de servicio", tone: "bad" },
};

export function AgentsCard({ agents }: { agents: Agent[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Agentes trabajando</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/agents" />}>
            Ver todos
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {agents.length === 0 ? (
          <p className="text-sm text-muted-foreground">El backend no devuelve agentes registrados.</p>
        ) : (
          <ul className="space-y-2">
            {agents.slice(0, 5).map((agent) => {
              const status = AGENT_STATUS[agent.status] ?? { label: agent.status, tone: "neutral" as LevelTone };
              return (
                <li key={agent.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
                  <span className="flex size-7 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
                    <Bot className="size-3.5" />
                  </span>
                  <span className="min-w-0 text-[13px] leading-tight">{agent.name}</span>
                  <LevelChip tone={status.tone}>{status.label}</LevelChip>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const RISK_TONE: Record<ProjectRiskRow["level"], LevelTone> = { Alto: "bad", Medio: "warn", Bajo: "ok" };

export function RisksCard({ risks }: { risks: ProjectRiskRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Riesgos</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="verified" compact tooltip="Los riesgos que cada agente dejó en su análisis, más el Legal Gate y el capital expuesto." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {risks.map((risk, index) => (
            <li key={`${risk.source}-${index}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2">
              {risk.level === "Bajo" ? (
                <Check className="mt-0.5 size-4 shrink-0 text-primary" />
              ) : (
                <ShieldAlert className={cn("mt-0.5 size-4 shrink-0", risk.level === "Alto" ? "text-destructive" : "text-warning")} />
              )}
              <span className="min-w-0 text-xs leading-tight">
                <span className="text-muted-foreground">{risk.source}: </span>
                {risk.text}
              </span>
              <LevelChip tone={RISK_TONE[risk.level]}>{risk.level}</LevelChip>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// --- Actividad, hitos, comparación y aprendizajes --------------------------------------

export function ActivityCard({ entries, limit = 6 }: { entries: AuditEntry[]; limit?: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Actividad reciente</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/audit" />}>
            Ver todo
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin actividad registrada para este proyecto.</p>
        ) : (
          <ul className="space-y-2">
            {entries.slice(0, limit).map((entry) => (
              <li key={entry.id} className="grid grid-cols-[3rem_minmax(0,1fr)] items-start gap-2 text-xs">
                <span className="text-muted-foreground tabular-nums">{formatTime(Date.parse(entry.created_at))}</span>
                <span className="min-w-0 leading-tight">
                  <span className="block font-medium">{entry.actor}</span>
                  <span className="block text-muted-foreground">{entry.action}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function MilestonesCard({ milestones }: { milestones: ProjectMilestone[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Hitos principales</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-xs">
          {milestones.map((milestone) => (
            <li key={milestone.label} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
              {milestone.done ? <Check className="size-4 shrink-0 text-primary" /> : <Clock className="size-4 shrink-0 text-muted-foreground" />}
              <span className={cn("min-w-0 leading-tight", !milestone.done && "text-muted-foreground")}>{milestone.label}</span>
              <span className="text-muted-foreground tabular-nums">{milestone.at ? formatDay(milestone.at) : "—"}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function formatComparison(row: ComparisonRow, value: number): string {
  if (row.format === "euro") return formatEuro(value, value >= 100 ? 0 : 2);
  if (row.format === "percent") return formatPercent(value);
  if (row.format === "days") return `${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`;
  return formatInteger(value);
}

export function PlannedVsActualCard({ rows }: { rows: ComparisonRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Resultado previsto vs real</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="Previsto: los supuestos de Economía. Real: los pedidos de demostración de Operaciones, porque no hay ventas reales." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal" />
              <th className="pb-2 text-right font-normal">Previsto</th>
              <th className="pb-2 text-right font-normal">Real</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const delta = row.planned !== 0 ? row.actual / row.planned - 1 : 0;
              const better = row.lowerIsBetter ? delta < 0 : delta > 0;
              return (
                <tr key={row.key} className="border-t">
                  <td className="py-1.5">{row.label}</td>
                  <td className="text-right text-muted-foreground tabular-nums">{formatComparison(row, row.planned)}</td>
                  <td className={cn("py-1.5 text-right tabular-nums", Math.abs(delta) < 0.02 ? "" : better ? "text-primary" : "text-warning")}>
                    {formatComparison(row, row.actual)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export function LearningsCard({ learnings, onApply }: { learnings: Learning[]; onApply?: () => void }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <GraduationCap className="size-4 text-primary" /> Aprendizajes del proyecto
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <ul className="space-y-1.5 text-xs">
          {learnings.map((learning) => (
            <li key={learning.text} className="flex items-start gap-2">
              {learning.tone === "ok" ? (
                <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />
              ) : (
                <Lightbulb className="mt-0.5 size-3.5 shrink-0 text-warning" />
              )}
              <span className="min-w-0 leading-tight">{learning.text}</span>
            </li>
          ))}
        </ul>
        <Button size="sm" variant="outline" className="w-full" disabled onClick={onApply} title="Pendiente: el backend no guarda aprendizajes del sistema">
          <span className="truncate">Aplicar al sistema</span> <ArrowRight />
        </Button>
      </CardContent>
    </Card>
  );
}

export function DocumentsCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="size-4 text-primary" /> Documentos
        </CardTitle>
        <CardDescription>Documentación del proyecto.</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay gestor documental: la lista es de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-xs">
          {DEMO_DOCUMENTS.map((document) => (
            <li key={document.name} className="flex items-center justify-between gap-2 py-2 first:pt-0">
              <span className="min-w-0">
                <span className="block leading-tight font-medium">{document.name}</span>
                <span className="block text-muted-foreground">{document.type}</span>
              </span>
              <LevelChip tone={document.state === "Generado" ? "ok" : document.state === "Borrador" ? "warn" : "neutral"}>{document.state}</LevelChip>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function ProjectFinanceCard({
  project,
  monthlyRevenue,
  unitContribution,
  capitalLimit,
}: {
  project: ProjectCard;
  monthlyRevenue: number;
  unitContribution: number;
  capitalLimit: number;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Finanzas del proyecto</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/cfo" />}>
            Ver en Finanzas
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm sm:grid-cols-2">
        {[
          ["Ingresos previstos", monthlyRevenue > 0 ? `${formatEuro(monthlyRevenue, 0)}/mes` : "—"],
          ["Beneficio previsto", project.projectedProfit !== null ? `${formatEuro(project.projectedProfit, 0)}/mes` : "—"],
          ["Beneficio real", project.realProfit !== null ? `${formatEuro(project.realProfit, 0)}/mes` : "Sin ventas reales"],
          ["Margen por unidad", unitContribution > 0 ? formatEuro(unitContribution) : "—"],
          ["Capital expuesto", formatEuro(project.capitalExposed, 0)],
          ["Límite de capital", formatEuro(capitalLimit, 0)],
        ].map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-2 rounded-lg border bg-background/40 px-2.5 py-1.5">
            <span className="text-xs text-muted-foreground">{label}</span>
            <span className="tabular-nums">{value}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
