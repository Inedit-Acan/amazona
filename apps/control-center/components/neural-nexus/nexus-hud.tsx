"use client";

import { STATUS_LABEL, type HudMetrics } from "@/lib/neural-nexus";
import { formatDuration, formatPercent } from "@/lib/format";
import { STATUS_COLOR } from "./nexus-theme";

/** Lo que enseña una cifra a la que le falta su fuente. No es un cero ni un valor de relleno. */
const NO_DATA = "Sin dato";

function Row({ label, value, missing }: { label: string; value: string; missing?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="min-w-0 truncate text-muted-foreground">{label}</span>
      <span className={missing ? "shrink-0 text-muted-foreground" : "shrink-0 tabular-nums"}>{value}</span>
    </div>
  );
}

/** Panel de métricas del Decision Engine (especificación §22). Cada cifra es un dato
 * del backend o dice «Sin dato»: no hay valores de demostración (M47 · Commit 1). */
export function NexusHud({ metrics, decisionUnavailable = false }: { metrics: HudMetrics; decisionUnavailable?: boolean }) {
  // Sin decisión y decisión que no se pudo leer NO son lo mismo: lo segundo es un error de lectura, no una ausencia.
  const withoutDecision = decisionUnavailable ? "No disponible" : "Sin decisión";
  const color = STATUS_COLOR[metrics.coreStatus];
  return (
    <div className="pointer-events-none w-56 rounded-xl border border-white/10 bg-[#071713]/85 p-3 backdrop-blur-sm">
      <p className="text-[11px] font-semibold tracking-wide text-foreground">DECISION ENGINE</p>
      <p className="mb-2.5 flex items-center gap-1.5 text-xs font-medium" style={{ color }}>
        <span className="size-1.5 rounded-full" style={{ background: color }} aria-hidden />
        {STATUS_LABEL[metrics.coreStatus]}
      </p>
      <div className="space-y-1.5">
        <Row
          label="Eventos activos"
          value={metrics.activeEvents === null ? (decisionUnavailable ? "No disponible" : NO_DATA) : String(metrics.activeEvents)}
          missing={metrics.activeEvents === null}
        />
        <Row label="Agentes activos" value={`${metrics.activeAgents} / ${metrics.totalAgents}`} />
        <Row
          label="Latencia media"
          value={metrics.latencyMs === null ? NO_DATA : formatDuration(metrics.latencyMs)}
          missing={metrics.latencyMs === null}
        />
        <Row label="Proyecto" value={metrics.projectName ?? withoutDecision} missing={metrics.projectName === null} />
      </div>
      <div className="mt-2.5 space-y-1">
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="text-muted-foreground">Progreso</span>
          <span className={metrics.progress === null ? "text-muted-foreground" : "tabular-nums"}>
            {metrics.progress === null ? withoutDecision : formatPercent(metrics.progress, 0)}
          </span>
        </div>
        {metrics.progress === null ? null : (
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(metrics.progress * 100)}%` }} />
          </div>
        )}
      </div>
    </div>
  );
}
