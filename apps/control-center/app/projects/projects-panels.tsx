"use client";

import Link from "next/link";
import {
  ArrowRight,
  Ban,
  Bot,
  Check,
  CircleDot,
  Clock,
  Gavel,
  LineChart,
  ShieldAlert,
  Slash,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { Agent, AuditEntry } from "@/lib/api";
import type { ProjectRisk } from "@/lib/projects";
import {
  NOT_CALCULATED,
  NO_DATA,
  PLAN_ABSENCE_TEXT,
  PLAN_NOTE,
  formatPlanAmount,
  formatPlanMargin,
  type NextStep,
  type ProjectCard,
  type ProjectMilestone,
} from "@/lib/projects-view";
import type { PipelineStep } from "@/lib/projects";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Las tarjetas de Proyectos (M45, Commit 11). Cada una enseña lo que el backend registró o dice que no lo tiene.
// Aquí no se importa `formatEuro`: ninguna cifra de esta pantalla viene con moneda declarada, y poner «€» sería
// asumirla. Tampoco hay ninguna tarjeta de demostración: las que había (documentos, «previsto vs real», minutos
// pendientes) se construían con constantes y con ruido determinista.

export function formatDay(ts: number): string {
  return new Date(ts).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

/** Fecha de un hecho registrado, o «Sin datos» cuando la auditoría no lo registró. */
export function formatDayOrNoData(ts: number | null): string {
  return ts === null ? NO_DATA : formatDay(ts);
}

const STAGE_ICON: Record<PipelineStep["state"], LucideIcon> = {
  done: Check,
  current: CircleDot,
  blocked: Ban,
  todo: Clock,
};

const STAGE_TONE: Record<PipelineStep["state"], LevelTone> = {
  done: "ok",
  current: "warn",
  blocked: "bad",
  todo: "neutral",
};

const STAGE_LABEL: Record<PipelineStep["state"], string> = {
  done: "Completada",
  current: "En curso",
  blocked: "Bloqueada",
  todo: "Pendiente",
};

// --- El grafo de tareas -------------------------------------------------------------------------------------------

export function PipelineStepper({ stages }: { stages: PipelineStep[] }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {stages.map((stage) => {
        const Icon = STAGE_ICON[stage.state];
        return (
          <li key={stage.task} className="min-w-0">
            <Link
              href={stage.href}
              className={cn(
                "flex min-w-0 flex-col items-center gap-1 rounded-xl border p-2 text-center transition hover:border-primary/50",
                stage.state === "done" && "border-primary/40 bg-primary/5",
                stage.state === "current" && "border-primary bg-primary/10",
                stage.state === "blocked" && "border-destructive/40 bg-destructive/5",
              )}
            >
              <span
                className={cn(
                  "flex size-7 items-center justify-center rounded-full border",
                  stage.state === "done" && "border-primary/50 bg-primary/20 text-primary",
                  stage.state === "current" && "border-primary bg-primary text-background",
                  stage.state === "blocked" && "border-destructive/50 bg-destructive/20 text-destructive",
                  stage.state === "todo" && "text-muted-foreground",
                )}
              >
                <Icon className="size-4" />
              </span>
              <span className="text-[11px] leading-tight font-medium">{stage.label}</span>
              <span
                className={cn(
                  "text-[11px] leading-tight",
                  stage.state === "blocked" ? "text-destructive" : stage.state === "current" ? "text-primary" : "text-muted-foreground",
                )}
              >
                {stage.recommendation ?? STAGE_LABEL[stage.state]}
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

export function StagesCard({ stages }: { stages: PipelineStep[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Etapas del grafo</CardTitle>
        <CardDescription>Las cuatro validaciones que el Director ejecutivo encarga por proyecto.</CardDescription>
        <CardAction>
          <DataProvenanceBadge
            status="verified"
            compact
            tooltip="El estado sale de la tarea del grafo y la recomendación de la evidencia que dejó el especialista."
          />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {stages.map((stage) => (
            <li key={stage.task} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0">
              <Link href={stage.href} className="min-w-0 font-medium text-primary underline-offset-4 hover:underline">
                {stage.label}
              </Link>
              <span className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{stage.recommendation ?? NO_DATA}</span>
                <LevelChip tone={STAGE_TONE[stage.state]}>{STAGE_LABEL[stage.state]}</LevelChip>
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// --- Lo siguiente, y la decisión --------------------------------------------------------------------------------

export function NextStepCard({ step }: { step: NextStep }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Lo siguiente</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status="verified"
            compact
            tooltip="La primera etapa del grafo que el backend no tiene completada. No es una recomendación nuestra."
          />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-primary/40 bg-primary/10 text-primary">
            <Sparkles className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="text-base leading-tight font-semibold">{step.title}</p>
            <p className="text-xs text-muted-foreground">
              {step.stage ? `Etapa: ${step.stage.label}` : "El grafo no deja ninguna etapa abierta."}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {step.href ? (
            <Button size="sm" variant="outline" nativeButton={false} render={<Link href={step.href} />}>
              Ver la pantalla de la etapa <ArrowRight />
            </Button>
          ) : null}
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

const DECISION_TONE: Record<string, LevelTone> = {
  GO: "ok",
  REVIEW: "warn",
  HUMAN_APPROVAL: "warn",
  NO_GO: "bad",
};

export function DecisionCard({ project }: { project: ProjectCard }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gavel className="size-4 text-primary" /> Decisión del Director ejecutivo
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="verified" compact tooltip="La decisión que el backend guarda para este proyecto, con su confianza y su razonamiento." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {project.decisionStatus === null ? (
          <p className="text-sm text-muted-foreground">
            Este proyecto todavía no tiene decisión registrada. Sin decisión no hay veredicto, ni confianza, ni riesgos
            que leer: {NO_DATA}.
          </p>
        ) : (
          <>
            <dl className="space-y-1.5 text-sm">
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Veredicto</dt>
                <dd>
                  <LevelChip tone={DECISION_TONE[project.decisionStatus] ?? "neutral"}>{project.decisionLabel}</LevelChip>
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Confianza</dt>
                <dd className="tabular-nums">{project.confidence === null ? NO_DATA : formatPlanMargin(project.confidence)}</dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Puntuación de oportunidad</dt>
                <dd className="tabular-nums">{project.opportunityScore === null ? NO_DATA : project.opportunityScore}</dd>
              </div>
            </dl>
            {project.rationale ? <p className="text-xs leading-snug text-muted-foreground">{project.rationale}</p> : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// --- La proyección (PLAN) ---------------------------------------------------------------------------------------

export function PlanCard({ project }: { project: ProjectCard }) {
  const amount = project.plannedMonthlyProfit;
  const margin = project.plannedMargin;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <LineChart className="size-4 text-warning" /> Proyección del proyecto
        </CardTitle>
        <CardDescription>Lo que el modelo espera si los supuestos se cumplen. No ha ocurrido.</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="planned" tooltip={PLAN_NOTE} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div className="flex items-center justify-between gap-2 rounded-lg border bg-background/40 px-2.5 py-1.5">
            <dt className="text-xs text-muted-foreground">Beneficio mensual proyectado</dt>
            <dd className="tabular-nums">{amount === null ? NO_DATA : formatPlanAmount(amount.value)}</dd>
          </div>
          <div className="flex items-center justify-between gap-2 rounded-lg border bg-background/40 px-2.5 py-1.5">
            <dt className="text-xs text-muted-foreground">Margen proyectado</dt>
            <dd className="tabular-nums">{margin === null ? NO_DATA : formatPlanMargin(margin.value)}</dd>
          </div>
        </dl>
        {project.planAbsence !== null ? (
          <p className="text-xs leading-snug text-muted-foreground">{PLAN_ABSENCE_TEXT[project.planAbsence]}</p>
        ) : null}
        <p className="text-[11px] leading-snug text-muted-foreground">{PLAN_NOTE}</p>
      </CardContent>
    </Card>
  );
}

// --- Lo que no se calcula ---------------------------------------------------------------------------------------

export function NotCalculatedCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Slash className="size-4 text-muted-foreground" /> Lo que esta pantalla no calcula
        </CardTitle>
        <CardDescription>Dicho una vez, para que ninguna ausencia parezca un descuido.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-xs">
          {NOT_CALCULATED.map((item) => (
            <li key={item.label} className="leading-snug">
              <span className="font-medium">{item.label}: </span>
              <span className="text-muted-foreground">{item.reason}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// --- Agentes, riesgos, hitos y actividad ------------------------------------------------------------------------

const AGENT_STATUS: Record<string, { label: string; tone: LevelTone }> = {
  AVAILABLE: { label: "Disponible", tone: "ok" },
  BUSY: { label: "Ejecutando", tone: "warn" },
  OFFLINE: { label: "Fuera de servicio", tone: "bad" },
};

export function AgentsCard({ agents }: { agents: Agent[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Agentes registrados</CardTitle>
        <CardDescription>Del sistema, no de este proyecto: el backend no enlaza agentes con un proyecto.</CardDescription>
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

export function RisksCard({ risks }: { risks: ProjectRisk[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Riesgos</CardTitle>
        <CardDescription>Los que cada especialista dejó escritos en la evidencia de la decisión.</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="verified" compact tooltip="Texto literal de la evidencia. Nadie gradúa su nivel, así que esta pantalla no lo inventa." />
        </CardAction>
      </CardHeader>
      <CardContent>
        {risks.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ningún especialista dejó riesgos escritos para este proyecto.</p>
        ) : (
          <ul className="space-y-2">
            {risks.map((risk, index) => (
              <li key={`${risk.stage}-${index}`} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning" />
                <span className="min-w-0 text-xs leading-tight">
                  <span className="text-muted-foreground">{risk.stage}: </span>
                  {risk.risk}
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
        <CardTitle>Hitos del proyecto</CardTitle>
        <CardDescription>Cada etapa con la fecha en que la auditoría registró que se completó.</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="verified" compact tooltip="La fecha es la de la entrada `task.completed` del registro de auditoría. Sin entrada, «Sin datos»." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-xs">
          {milestones.map((milestone) => (
            <li key={milestone.task} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
              {milestone.state === "done" ? (
                <Check className="size-4 shrink-0 text-primary" />
              ) : (
                <Clock className="size-4 shrink-0 text-muted-foreground" />
              )}
              <span className={cn("min-w-0 leading-tight", milestone.state !== "done" && "text-muted-foreground")}>{milestone.label}</span>
              <span className="text-muted-foreground tabular-nums">{formatDayOrNoData(milestone.at)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function ActivityCard({ entries, limit = 6 }: { entries: AuditEntry[]; limit?: number }) {
  const sorted = [...entries].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Actividad registrada</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/audit" />}>
            Ver todo
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin actividad registrada para este proyecto.</p>
        ) : (
          <ul className="space-y-2">
            {sorted.slice(0, limit).map((entry) => (
              <li key={entry.id} className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-start gap-2 text-xs">
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
