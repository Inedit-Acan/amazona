"use client";

import { ArrowRight, type LucideIcon } from "lucide-react";
import { relativeTime } from "@/lib/dates";
import { formatDuration, formatEuro, formatPercent } from "@/lib/format";
import { ACTIVITY_LABEL, type AgentCardView } from "@/lib/agents-view";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const ACTIVITY_TONE: Record<AgentCardView["activity"], LevelTone> = {
  running: "ok",
  available: "neutral",
  waiting: "warn",
  offline: "bad",
};

/** Tarjeta de un agente de la flota (mockup docs/design/agentes.png): estado,
 * lo que mide el log de ejecuciones (éxito, latencia), lo que aporta la
 * demostración (evaluación, coste, tarea en curso) y su versión. Solo presenta
 * el modelo que recibe. */
export function AgentCard({
  agent,
  icon: Icon,
  now,
  expanded,
  onToggle,
}: {
  agent: AgentCardView;
  icon: LucideIcon;
  now: number;
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const metrics: [string, string][] = [
    ["Éxito", agent.successRate === null ? "—" : formatPercent(agent.successRate)],
    ["Eval.", `${agent.evalScore}/100`],
    ["Latencia", agent.avgLatencyMs === null ? "—" : formatDuration(agent.avgLatencyMs)],
    ["Coste hoy", formatEuro(agent.costToday)],
  ];

  return (
    <Card className="min-w-0 gap-0 py-3">
      <CardContent className="space-y-2.5 px-3">
        <div className="flex items-start gap-2.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary">
            <Icon className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-1.5">
              <p className="text-[15px] leading-tight font-semibold">{agent.name}</p>
              <LevelChip tone={ACTIVITY_TONE[agent.activity]}>{ACTIVITY_LABEL[agent.activity]}</LevelChip>
            </div>
            <p className="mt-1 text-xs leading-tight text-muted-foreground">{agent.description}</p>
          </div>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2">
          <dl className="space-y-1 text-xs">
            {metrics.map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="min-w-0 space-y-1 text-xs">
            <p className="text-muted-foreground">{agent.currentTask ? "Tarea en curso" : "Última tarea"}</p>
            <p className="leading-tight font-medium break-words">
              {agent.currentTask ?? (agent.lastActivityAt ? agent.capabilities[0] ?? "Ejecución" : "Sin ejecuciones")}
            </p>
            {agent.currentTask ? (
              <>
                <span className="block h-1.5 rounded-full bg-muted">
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round((agent.taskProgress ?? 0) * 100)}%` }} />
                </span>
                <p className="text-right text-muted-foreground tabular-nums">{formatPercent(agent.taskProgress ?? 0, 0)}</p>
              </>
            ) : (
              <p className={cn("text-muted-foreground", agent.lastActivityAt === null && "italic")}>
                {agent.lastActivityAt === null ? "El log no registra ejecuciones" : `${agent.runs} ejecuciones registradas`}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-[11px] text-muted-foreground">
          <span>
            v{agent.version}
            {agent.lastActivityAt !== null ? ` · ${relativeTime(agent.lastActivityAt, now)}` : ""}
          </span>
          <Button size="xs" variant="outline" onClick={onToggle} aria-expanded={expanded}>
            {expanded ? "Ocultar" : "Ver agente"} <ArrowRight />
          </Button>
        </div>

        {expanded ? (
          <dl className="space-y-1.5 rounded-lg border bg-background/40 p-2.5 text-xs">
            <div>
              <dt className="text-muted-foreground">Capacidades</dt>
              <dd className="mt-0.5 flex flex-wrap gap-1">
                {agent.capabilities.length === 0 ? (
                  <span className="text-muted-foreground">Sin capacidades registradas</span>
                ) : (
                  agent.capabilities.map((capability) => (
                    <span key={capability} className="rounded-md border px-1.5 py-0.5 font-mono text-[10px]">
                      {capability}
                    </span>
                  ))
                )}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Herramientas (demo)</dt>
              <dd className="mt-0.5">{agent.tools.join(" · ")}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Ejecuciones hoy</dt>
              <dd className="tabular-nums">{agent.runsToday}</dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-muted-foreground">Rol</dt>
              <dd className="font-mono text-[10px]">{agent.role}</dd>
            </div>
          </dl>
        ) : null}
      </CardContent>
    </Card>
  );
}
