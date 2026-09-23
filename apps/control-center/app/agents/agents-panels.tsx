"use client";

import Link from "next/link";
import { AlertTriangle, BookOpen, CircleCheck, FlaskConical, GitBranch, KeyRound, Settings2 } from "lucide-react";
import { DEMO_RESOURCES } from "@/lib/demo/agents";
import { relativeTime } from "@/lib/dates";
import { formatDuration, formatEuro, formatInteger, formatPercent } from "@/lib/format";
import type { ActivityEntry, AgentCardView, FleetAlert, UsagePoint } from "@/lib/agents-view";
import { versionHistory } from "@/lib/agents-view";
import { BarChart } from "@/components/bar-chart";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { DonutChart } from "@/components/donut-chart";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { RankedBars } from "@/components/ranked-bars";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const RESOURCE_ICON: Record<string, typeof BookOpen> = {
  docs: BookOpen,
  eval: FlaskConical,
  version: GitBranch,
  permissions: KeyRound,
};

// --- Barra lateral -----------------------------------------------------------------

export function RealtimeActivityCard({ entries, now, isDemo }: { entries: ActivityEntry[]; now: number; isDemo: boolean }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Actividad en tiempo real</CardTitle>
        <CardAction>
          {isDemo ? (
            <DataProvenanceBadge status="demo" compact tooltip="El log de ejecuciones del backend está vacío: la actividad es de demostración." />
          ) : (
            <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/audit" />}>
              Ver todas
            </Button>
          )}
        </CardAction>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">El log de ejecuciones está vacío.</p>
        ) : (
          <ul className="space-y-2.5">
            {entries.map((entry) => (
              <li key={entry.id} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
                <span className={cn("mt-1 size-2 shrink-0 rounded-full", entry.success ? "bg-primary" : "bg-destructive")} aria-hidden />
                <span className="min-w-0 text-xs leading-tight">
                  <span className="block font-medium">{entry.agent}</span>
                  <span className="block text-muted-foreground">
                    {entry.capability} · {formatDuration(entry.durationMs)}
                  </span>
                  <span className="block text-muted-foreground">{relativeTime(entry.at, now)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const ALERT_TONE: Record<FleetAlert["level"], LevelTone> = { Alta: "bad", Media: "warn" };

export function FleetAlertsCard({ alerts }: { alerts: FleetAlert[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Alertas</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="estimated" compact tooltip="Se derivan del log de ejecuciones (errores y latencia) y del coste de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        {alerts.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CircleCheck className="size-4 text-primary" /> Ninguna alerta abierta.
          </p>
        ) : (
          <ul className="space-y-2">
            {alerts.slice(0, 5).map((alert) => (
              <li key={alert.key} className="grid grid-cols-[3.2rem_minmax(0,1fr)] items-start gap-2">
                <LevelChip tone={ALERT_TONE[alert.level]}>{alert.level}</LevelChip>
                <span className="min-w-0 text-xs leading-tight">
                  <span className="block font-medium">{alert.agent}</span>
                  <span className="block text-muted-foreground">{alert.message}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
        <Button size="sm" variant="outline" className="w-full" disabled title="Pendiente: el backend no guarda umbrales de alerta">
          <Settings2 /> Configurar alertas
        </Button>
      </CardContent>
    </Card>
  );
}

export function ResourcesCard() {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Recursos</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="pending" compact tooltip="Documentación, evaluaciones, versiones y permisos todavía no existen en el backend." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {DEMO_RESOURCES.map((resource) => {
            const Icon = RESOURCE_ICON[resource.key] ?? BookOpen;
            return (
              <li key={resource.key} className="flex items-start gap-2 rounded-lg border p-2 opacity-80" title="Pendiente de backend">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
                  <Icon className="size-3.5" />
                </span>
                <span className="min-w-0 text-xs leading-tight">
                  <span className="block font-medium">{resource.title}</span>
                  <span className="block text-muted-foreground">{resource.detail}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

// --- Gráficos ------------------------------------------------------------------------

export function UsageCard({ points, isDemo }: { points: UsagePoint[]; isDemo: boolean }) {
  const totalRuns = points.reduce((sum, point) => sum + point.runs, 0);
  const totalCost = points.reduce((sum, point) => sum + point.cost, 0);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>
          Uso y coste de agentes <span className="font-normal text-muted-foreground">(últimos 7 días)</span>
        </CardTitle>
        <CardDescription>
          {formatInteger(totalRuns)} ejecuciones · coste estimado {formatEuro(totalCost)}
        </CardDescription>
        <CardAction>
          <DataProvenanceBadge status={isDemo ? "demo" : "estimated"} compact tooltip={isDemo ? "Ejecuciones y coste de demostración: el log del backend está vacío." : "Las ejecuciones son reales; el coste es el de demostración por equipo (el backend registra 0)."} />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        {totalRuns === 0 ? (
          <p className="text-sm text-muted-foreground">Sin ejecuciones en la última semana.</p>
        ) : (
          <>
            <BarChart
              ariaLabel="Ejecuciones por día"
              data={points.map((point) => ({ key: String(point.offset), label: point.label, value: point.runs, highlight: point.offset === 0 }))}
              formatValue={(value) => formatInteger(value)}
              valueHeader="Ejecuciones"
            />
            <div className="flex items-center justify-between gap-2 border-t pt-2 text-xs text-muted-foreground">
              <span>Coste diario</span>
              <span className="flex items-center gap-2">
                <Sparkline values={points.map((point) => point.cost)} />
                <span className="tabular-nums">{formatEuro(points.at(-1)?.cost ?? 0)}</span>
              </span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const TEAM_COLORS = ["#00d69a", "#4f8df7", "#f2c94c", "#e056c8", "#f2994a", "#a8a4f0", "#5aa9e6", "#e05c5c", "#7a8b99"];

export function DistributionCard({ rows, isDemo }: { rows: { team: string; runs: number }[]; isDemo: boolean }) {
  const total = rows.reduce((sum, row) => sum + row.runs, 0);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Distribución de ejecuciones</CardTitle>
        <CardAction>
          <DataProvenanceBadge status={isDemo ? "demo" : "verified"} compact tooltip={isDemo ? "Ejecuciones de demostración por equipo: el log del backend está vacío." : "Ejecuciones registradas por equipo del agente."} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-4">
        {total === 0 ? (
          <p className="text-sm text-muted-foreground">Sin ejecuciones registradas.</p>
        ) : (
          <>
            <DonutChart
              ariaLabel="Ejecuciones por equipo"
              segments={rows.map((row, k) => ({ key: row.team, value: row.runs, color: TEAM_COLORS[k % TEAM_COLORS.length] }))}
              centerLabel={formatInteger(total)}
              centerCaption="Total"
              size={120}
            />
            <ul className="min-w-36 flex-1 space-y-1 text-xs">
              {rows.map((row, k) => (
                <li key={row.team} className="grid grid-cols-[auto_minmax(0,1fr)_2.6rem] items-center gap-2">
                  <span className="size-2.5 rounded-full" style={{ background: TEAM_COLORS[k % TEAM_COLORS.length] }} aria-hidden />
                  <span className="truncate">{row.team}</span>
                  <span className="text-right tabular-nums">{formatPercent(row.runs / total, 0)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function CostByAgentCard({ rows }: { rows: { key: string; label: string; value: number }[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>
          Coste por agente <span className="font-normal text-muted-foreground">(hoy)</span>
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="El coste por ejecución es de demostración: el registro devuelve 0." />
        </CardAction>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ningún agente ha ejecutado nada hoy.</p>
        ) : (
          <RankedBars
            ariaLabel="Coste por agente hoy"
            items={rows.slice(0, 8).map((row) => ({ key: row.key, label: row.label, value: row.value, valueLabel: formatEuro(row.value) }))}
          />
        )}
      </CardContent>
    </Card>
  );
}

// --- Pestañas de tabla -----------------------------------------------------------------

export function ActivityTable({ entries, now, isDemo }: { entries: ActivityEntry[]; now: number; isDemo: boolean }) {
  const columns: DataTableColumn<ActivityEntry>[] = [
    { key: "agent", header: "Agente", cell: (row) => <span className="font-medium">{row.agent}</span>, sortValue: (row) => row.agent, exportValue: (row) => row.agent },
    { key: "team", header: "Equipo", cell: (row) => row.team, sortValue: (row) => row.team, exportValue: (row) => row.team },
    { key: "capability", header: "Capacidad", cell: (row) => <span className="font-mono text-xs">{row.capability}</span>, sortValue: (row) => row.capability, exportValue: (row) => row.capability },
    {
      key: "success",
      header: "Resultado",
      cell: (row) => <LevelChip tone={row.success ? "ok" : "bad"}>{row.success ? "Correcta" : "Fallida"}</LevelChip>,
      sortValue: (row) => (row.success ? 1 : 0),
      exportValue: (row) => (row.success ? "Correcta" : "Fallida"),
    },
    { key: "duration", header: "Latencia", cell: (row) => formatDuration(row.durationMs), sortValue: (row) => row.durationMs, exportValue: (row) => row.durationMs, align: "right" },
    { key: "at", header: "Cuándo", cell: (row) => relativeTime(row.at, now), sortValue: (row) => row.at, exportValue: (row) => new Date(row.at).toISOString() },
  ];
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Ejecuciones {isDemo ? "de demostración" : "registradas"}</CardTitle>
        <CardAction>
          <DataProvenanceBadge status={isDemo ? "demo" : "verified"} compact tooltip={isDemo ? "El log del backend está vacío: estas ejecuciones son de demostración." : "Log de ejecuciones del CEO (AgentExecutionLog)."} />
        </CardAction>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={entries}
          getRowId={(row) => row.id}
          getSearchText={(row) => `${row.agent} ${row.capability} ${row.team}`}
          searchPlaceholder="Buscar agente o capacidad…"
          exportFileName="ejecuciones-agentes"
          emptyMessage="El log de ejecuciones está vacío."
        />
      </CardContent>
    </Card>
  );
}

export function PerformanceTable({ cards, isDemo }: { cards: AgentCardView[]; isDemo: boolean }) {
  const columns: DataTableColumn<AgentCardView>[] = [
    { key: "name", header: "Agente", cell: (row) => <span className="font-medium">{row.name}</span>, sortValue: (row) => row.name, exportValue: (row) => row.name },
    { key: "team", header: "Equipo", cell: (row) => row.team, sortValue: (row) => row.team, exportValue: (row) => row.team },
    { key: "runs", header: "Ejecuciones", cell: (row) => formatInteger(row.runs), sortValue: (row) => row.runs, exportValue: (row) => row.runs, align: "right" },
    {
      key: "success",
      header: "Éxito",
      cell: (row) => (row.successRate === null ? "—" : formatPercent(row.successRate)),
      sortValue: (row) => row.successRate ?? -1,
      exportValue: (row) => (row.successRate === null ? "" : row.successRate),
      align: "right",
    },
    {
      key: "latency",
      header: "Latencia media",
      cell: (row) => (row.avgLatencyMs === null ? "—" : formatDuration(row.avgLatencyMs)),
      sortValue: (row) => row.avgLatencyMs ?? -1,
      exportValue: (row) => row.avgLatencyMs ?? "",
      align: "right",
    },
    { key: "cost", header: "Coste hoy", cell: (row) => formatEuro(row.costToday), sortValue: (row) => row.costToday, exportValue: (row) => row.costToday, align: "right" },
  ];
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rendimiento por agente</CardTitle>
        <CardAction>
          <DataProvenanceBadge status={isDemo ? "demo" : "estimated"} compact tooltip={isDemo ? "Sin log real: ejecuciones, éxito, latencia y coste son de demostración." : "Ejecuciones, éxito y latencia son reales; el coste es de demostración."} />
        </CardAction>
      </CardHeader>
      <CardContent>
        <DataTable
          columns={columns}
          rows={cards}
          getRowId={(row) => row.id}
          getSearchText={(row) => `${row.name} ${row.team}`}
          searchPlaceholder="Buscar agente…"
          exportFileName="rendimiento-agentes"
          emptyMessage="No hay agentes registrados."
        />
      </CardContent>
    </Card>
  );
}

export function EvaluationsTable({ cards }: { cards: AgentCardView[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Evaluaciones</CardTitle>
        <CardDescription>Puntuación de la última evaluación de cada agente.</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No existe suite de evaluación en el backend: las puntuaciones son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="divide-y text-sm">
          {cards.map((card) => (
            <li key={card.id} className="grid grid-cols-[minmax(0,1fr)_minmax(3rem,8rem)_3.5rem] items-center gap-3 py-2 first:pt-0">
              <span className="min-w-0">
                <span className="block leading-tight font-medium">{card.name}</span>
                <span className="block text-xs text-muted-foreground">{card.team}</span>
              </span>
              <span className="h-1.5 rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${card.evalScore}%` }} />
              </span>
              <span className="text-right text-sm tabular-nums">{card.evalScore}/100</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function VersionsTable({ cards }: { cards: AgentCardView[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Versiones</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="estimated" compact tooltip="La versión en uso es real; las anteriores y sus notas son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {cards.map((card) => (
            <li key={card.id} className="min-w-0">
              <p className="text-sm font-medium">{card.name}</p>
              <ul className="mt-1 space-y-1 text-xs">
                {versionHistory(card).map((row) => (
                  <li key={row.version} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <span className="font-mono">v{row.version}</span>
                      {row.current ? <LevelChip tone="ok">En uso</LevelChip> : null}
                    </span>
                    <span className="text-muted-foreground">{row.note}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export const AGENTS_ALERT_ICON = AlertTriangle;
