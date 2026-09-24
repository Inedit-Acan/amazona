"use client";

import { DEMO_CORE_METRICS } from "@/lib/demo/neural-nexus";
import { STATUS_LABEL, type HudMetrics } from "@/lib/neural-nexus";
import { formatDuration, formatPercent } from "@/lib/format";
import { STATUS_COLOR } from "./nexus-theme";

function Row({ label, value, demo }: { label: string; value: string; demo?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="min-w-0 truncate text-muted-foreground">{label}</span>
      <span className="shrink-0 tabular-nums" title={demo ? "Dato de demostración" : undefined}>
        {value}
        {demo ? <span className="ml-1 text-[10px] text-muted-foreground">demo</span> : null}
      </span>
    </div>
  );
}

/** Panel de métricas del Decision Engine (especificación §22). Cada línea dice
 * si el dato es real o de demostración. */
export function NexusHud({ metrics }: { metrics: HudMetrics }) {
  const color = STATUS_COLOR[metrics.coreStatus];
  return (
    <div className="pointer-events-none w-56 rounded-xl border border-white/10 bg-[#071713]/85 p-3 backdrop-blur-sm">
      <p className="text-[11px] font-semibold tracking-wide text-foreground">DECISION ENGINE</p>
      <p className="mb-2.5 flex items-center gap-1.5 text-xs font-medium" style={{ color }}>
        <span className="size-1.5 rounded-full" style={{ background: color }} aria-hidden />
        {STATUS_LABEL[metrics.coreStatus]}
      </p>
      <div className="space-y-1.5">
        <Row label="Eventos activos" value={String(metrics.activeEvents)} demo={metrics.activeEventsAreDemo} />
        <Row label="Agentes activos" value={`${metrics.activeAgents} / ${metrics.totalAgents}`} />
        <Row
          label="Latencia media"
          value={metrics.latencyMs === null ? formatDuration(DEMO_CORE_METRICS.latencyMs) : formatDuration(metrics.latencyMs)}
          demo={metrics.latencyMs === null}
        />
        <Row label="Proyecto" value={metrics.projectName} demo={!metrics.projectIsReal} />
      </div>
      <div className="mt-2.5 space-y-1">
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="text-muted-foreground">Progreso</span>
          <span className="tabular-nums">
            {formatPercent(metrics.progress, 0)}
            {metrics.progressIsReal ? null : <span className="ml-1 text-[10px] text-muted-foreground">demo</span>}
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(metrics.progress * 100)}%` }} />
        </div>
      </div>
    </div>
  );
}
