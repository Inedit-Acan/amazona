"use client";

import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleDot,
  Clock,
  ExternalLink,
  Headset,
  RotateCcw,
  Settings2,
  Truck,
} from "lucide-react";
import {
  DEMO_AUTOMATIONS,
  DEMO_RETURN_TARGET,
  OPERATING_MODES,
  type OperatingMode,
} from "@/lib/demo/operations";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import {
  ORDER_STATUS_LABEL,
  orderDurations,
  orderTimeline,
  type CarrierRow,
  type IncidentView,
  type MapNode,
  type Order,
  type ReturnsView,
  type SupplierPerformanceRow,
} from "@/lib/operations-view";
import type { OperationsRecord, ReturnPolicy, SupportTicketExample } from "@/lib/api";
import { ticketTriage } from "@/lib/operations";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Flag, regionFlag } from "@/components/flag";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { RingGauge } from "@/components/ring-gauge";
import { RouteMap } from "@/components/route-map";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const SEVERITY_TONE: Record<IncidentView["severity"], LevelTone> = { "Crítica": "bad", Alta: "warn", Media: "neutral" };

/** Fecha corta en UTC: los pedidos se generan a medianoche UTC, así que el
 * servidor y el navegador escriben exactamente el mismo día. */
export function formatDay(ts: number): string {
  return new Date(ts).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
}

function formatSpan(ms: number): string {
  const hours = ms / 3_600_000;
  if (hours < 24) return `${Math.round(hours)} h`;
  const days = hours / 24;
  return `${days.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días`;
}

// --- Centro de incidencias -----------------------------------------------------

export function IncidentsCard({
  incidents,
  selectedId,
  onSelect,
  ticket,
}: {
  incidents: IncidentView[];
  selectedId: string | null;
  onSelect: (orderId: string) => void;
  /** Ticket de ejemplo del agente de operaciones, si guardó alguno (dato real). */
  ticket?: SupportTicketExample;
}) {
  const triage = ticket ? ticketTriage(ticket) : null;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          Centro de incidencias
          <LevelChip tone={incidents.length > 0 ? "bad" : "ok"}>
            {incidents.length} {incidents.length === 1 ? "abierta" : "abiertas"}
          </LevelChip>
        </CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay incidencias reales: se derivan de los pedidos de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        {incidents.length === 0 ? (
          <p className="text-sm text-muted-foreground">Ninguna incidencia abierta en el periodo.</p>
        ) : (
          <ul className="space-y-2">
            {incidents.slice(0, 5).map((incident) => (
              <li key={incident.order.id}>
                <button
                  type="button"
                  onClick={() => onSelect(incident.order.id)}
                  aria-pressed={selectedId === incident.order.id}
                  className={cn(
                    "grid w-full grid-cols-[4.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-lg border p-2 text-left transition",
                    selectedId === incident.order.id ? "border-primary/60 bg-primary/5" : "hover:border-primary/40",
                  )}
                >
                  <LevelChip tone={SEVERITY_TONE[incident.severity]} className="uppercase">
                    {incident.severity}
                  </LevelChip>
                  <span className="min-w-0">
                    <span className="block text-[13px] leading-tight font-medium">{incident.title}</span>
                    <span className="block text-xs text-muted-foreground">
                      #{incident.order.id} · {incident.detail}
                    </span>
                  </span>
                  <span
                    className="rounded-md border px-2 py-1 text-xs text-muted-foreground"
                    title={`Pendiente: no existe gestión de incidencias en el backend (${incident.action.toLowerCase()})`}
                  >
                    {incident.action}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {triage ? (
          <p className="flex flex-wrap items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 p-2 text-[11px]">
            <Headset className="size-3.5 shrink-0 text-primary" />
            <span className="font-medium text-primary">Triaje de soporte del agente:</span>
            <span className="text-muted-foreground">
              {triage.detail} · {triage.label}
            </span>
            <DataProvenanceBadge status="estimated" compact tooltip="Ticket de ejemplo que generó el agente de operaciones para este producto." />
          </p>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          Al elegir una incidencia se abre su pedido en «Seguimiento del pedido». Resolver, investigar o gestionar
          necesita backend.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Mapa logístico ------------------------------------------------------------

const MAP_TONE_LABEL: { tone: "ok" | "warn" | "bad"; color: string; label: string }[] = [
  { tone: "ok", color: "var(--emerald-bright)", label: "Normal" },
  { tone: "warn", color: "var(--warning)", label: "Retraso" },
  { tone: "bad", color: "var(--danger)", label: "Incidencia" },
];

export function LogisticsMapCard({ nodes, routes }: { nodes: MapNode[]; routes: { id: string; from: string; to: string }[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Mapa logístico</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="Pedidos y tiempos por región derivados de los pedidos de demostración; el origen del proveedor sí es real." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <RouteMap
          ariaLabel="Mapa de pedidos por origen y destino"
          points={nodes.map((n) => ({
            id: n.id,
            label: n.label,
            lonLat: n.lonLat,
            kind: n.kind,
            tone: n.tone,
            caption: [`${formatInteger(n.orders)} pedidos`, `${n.avgDays.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días de media`],
          }))}
          routes={routes}
          legend={MAP_TONE_LABEL.map((t) => ({ color: t.color, label: t.label }))}
          className="overflow-hidden rounded-xl border bg-background/40"
        />
      </CardContent>
    </Card>
  );
}

// --- Seguimiento del pedido -----------------------------------------------------

export function OrderTrackingCard({ order, record }: { order: Order | undefined; record?: OperationsRecord }) {
  if (!order) {
    return (
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Seguimiento del pedido</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Elige un pedido en la tabla o en una incidencia.</p>
        </CardContent>
      </Card>
    );
  }
  const steps = orderTimeline(order, record);
  const durations = orderDurations(steps);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Seguimiento del pedido</CardTitle>
        <CardAction>
          <DataProvenanceBadge
            status={record ? "estimated" : "demo"}
            compact
            tooltip={
              record
                ? "Los hitos vienen del seguimiento simulado que guardó el agente de operaciones para este producto y mercado."
                : "Pedido de demostración: no hay seguimiento real del transportista."
            }
          />
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <div>
            <p className="text-lg font-semibold">#{order.id}</p>
            <p className="text-xs text-muted-foreground">
              {order.channel} · {order.units} {order.units === 1 ? "artículo" : "artículos"} · {formatEuro(order.amount)}
            </p>
          </div>
          <div className="flex gap-3 rounded-lg border bg-background/40 p-3">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-lg border bg-background/60 text-primary">
              <Truck className="size-6" />
            </span>
            <div className="min-w-0 text-xs">
              <p className="text-[13px] font-medium">{order.productName}</p>
              <p className="text-muted-foreground">SKU: {order.sku}</p>
              <p className="text-muted-foreground">Cliente: {order.customer}</p>
              <p className="flex items-center gap-1.5 text-muted-foreground">
                {regionFlag(order.supplierRegion) ? <Flag code={regionFlag(order.supplierRegion)!} /> : null}
                {order.supplierName}
              </p>
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-2 rounded-lg border bg-background/40 p-3 text-xs">
            <div>
              <dt className="text-muted-foreground">Procesamiento</dt>
              <dd className="mt-0.5 font-medium">{formatSpan(durations.processing)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Recogida</dt>
              <dd className="mt-0.5 font-medium">{formatSpan(durations.pickup)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Tránsito estimado</dt>
              <dd className="mt-0.5 font-medium">{formatSpan(durations.transit)}</dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" nativeButton={false} render={<Link href={`/audit?q=${order.productId}`} />}>
              Ver historial completo <ArrowRight />
            </Button>
            <Button size="sm" variant="ghost" disabled title="Pendiente: no hay integración con transportistas">
              Ver en transportista <ExternalLink />
            </Button>
          </div>
        </div>

        <ol className="min-w-0 space-y-3">
          {steps.map((step) => (
            <li key={step.key} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 text-xs">
              {step.done ? (
                <CheckCircle2 className="size-4 shrink-0 text-primary" />
              ) : step.current ? (
                <CircleDot className="size-4 shrink-0 text-primary" />
              ) : (
                <Clock className="size-4 shrink-0 text-muted-foreground" />
              )}
              <span className={cn("min-w-0 leading-tight", step.current ? "font-semibold text-primary" : step.done ? "" : "text-muted-foreground")}>
                {step.label}
              </span>
              <span className="text-right text-muted-foreground tabular-nums">{formatDay(step.at)}</span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

// --- Rendimiento de proveedores y transportistas ---------------------------------

export function SupplierPerformanceCard({ rows }: { rows: SupplierPerformanceRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rendimiento de proveedores</CardTitle>
        <CardAction>
          <Button size="xs" variant="outline" className="text-primary" nativeButton={false} render={<Link href="/sourcing" />}>
            Ver todos
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Proveedor</th>
              <th className="pb-2 text-right font-normal">Pedidos</th>
              <th className="pb-2 text-right font-normal">A tiempo</th>
              <th className="pb-2 text-right font-normal">Defectos</th>
              <th className="pb-2 text-right font-normal">Score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="py-1.5">
                  <span className="flex items-center gap-1.5">
                    {regionFlag(row.region) ? <Flag code={regionFlag(row.region)!} /> : null}
                    <span className="leading-tight">{row.name}</span>
                  </span>
                </td>
                <td className="text-right tabular-nums">{formatInteger(row.orders)}</td>
                <td className="text-right tabular-nums">{formatPercent(row.onTimeRate)}</td>
                <td className="text-right tabular-nums">{formatPercent(row.defectRate)}</td>
                <td className="py-1.5 text-right">
                  <LevelChip tone={row.score >= 90 ? "ok" : row.score >= 75 ? "warn" : "bad"}>{row.score}</LevelChip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-muted-foreground">
          Origen y fiabilidad salen de la cotización real; los pedidos, la puntualidad y los defectos son de demostración.
        </p>
      </CardContent>
    </Card>
  );
}

export function CarriersCard({ rows }: { rows: CarrierRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Rendimiento de transportistas</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay integración con transportistas: puntualidad y tiempos son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 text-left font-normal">Transportista</th>
              <th className="pb-2 text-right font-normal">Pedidos</th>
              <th className="pb-2 text-right font-normal">Entrega a tiempo</th>
              <th className="pb-2 text-right font-normal">Tiempo medio</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-t">
                <td className="py-1.5">{row.name}</td>
                <td className="text-right tabular-nums">{formatInteger(row.orders)}</td>
                <td className={cn("text-right tabular-nums", row.onTimeRate < 0.9 && "text-destructive")}>{formatPercent(row.onTimeRate)}</td>
                <td className="text-right tabular-nums">{row.avgDays.toLocaleString("es-ES", { maximumFractionDigits: 1 })} días</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// --- Devoluciones ----------------------------------------------------------------

export function ReturnsCard({ view, policy }: { view: ReturnsView; policy?: ReturnPolicy }) {
  const max = Math.max(...view.reasons.map((r) => r.share), 0.01);
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Devoluciones</CardTitle>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="No hay devoluciones reales: motivos y estados son de demostración." />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="text-center">
            <RingGauge
              value={Math.min(1, view.rate / (DEMO_RETURN_TARGET * 2))}
              size={96}
              centerLabel={formatPercent(view.rate)}
              caption={view.rate <= DEMO_RETURN_TARGET ? "En objetivo" : "Sobre objetivo"}
            />
            <p className="mt-1 text-[11px] text-muted-foreground">Objetivo &lt; {formatPercent(DEMO_RETURN_TARGET, 0)}</p>
          </div>
          <ul className="min-w-40 flex-1 space-y-1.5 text-xs">
            {view.reasons.map((reason) => (
              <li key={reason.label} className="grid grid-cols-[minmax(0,1fr)_2.5rem] items-center gap-2">
                <span className="min-w-0">
                  <span className="block truncate">{reason.label}</span>
                  <span className="mt-0.5 block h-1.5 rounded-full bg-muted">
                    <span className="block h-full rounded-full bg-destructive/70" style={{ width: `${Math.round((reason.share / max) * 100)}%` }} />
                  </span>
                </span>
                <span className="text-right tabular-nums">{formatPercent(reason.share, 0)}</span>
              </li>
            ))}
          </ul>
        </div>
        {policy ? (
          <p className="flex flex-wrap items-center gap-1.5 rounded-lg border p-2 text-[11px] text-muted-foreground">
            <span className="font-medium text-foreground">Política del agente:</span>
            {policy.eligibility_window_days} días para devolver · comisión de reposición {formatPercent(policy.restocking_fee_percent / 100, 0)}
            {policy.refund_estimate !== null ? ` · reembolso estimado ${formatEuro(policy.refund_estimate)}` : ""}
            <DataProvenanceBadge status="estimated" compact tooltip="Política que calculó el agente de operaciones para este producto." />
          </p>
        ) : null}
        <dl className="grid grid-cols-4 gap-2 border-t pt-3 text-center text-xs">
          {view.states.map((state) => (
            <div key={state.key}>
              <dt className="text-muted-foreground">{state.label}</dt>
              <dd className="mt-0.5 text-base font-semibold">{state.count}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

// --- Operational Health ----------------------------------------------------------

export function HealthCard({ health }: { health: { score: number; label: string; axes: { label: string; value: number }[] } }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Operational Health</CardTitle>
      </CardHeader>
      <CardContent className="flex items-center gap-4">
        <RingGauge value={health.score / 100} size={104} centerLabel={`${health.score}/100`} caption={health.label} />
        <ul className="min-w-0 flex-1 space-y-1.5 text-xs">
          {health.axes.map((axis) => (
            <li key={axis.label} className="grid grid-cols-[minmax(0,5.5rem)_1fr_1.75rem] items-center gap-2">
              <span className="truncate text-muted-foreground">{axis.label}</span>
              <span className="h-1.5 rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${axis.value}%` }} />
              </span>
              <span className="text-right tabular-nums">{axis.value}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// --- Automatizaciones ------------------------------------------------------------

export function AutomationsCard({ mode, onModeChange }: { mode: OperatingMode; onModeChange: (mode: OperatingMode) => void }) {
  const current = OPERATING_MODES.find((m) => m.value === mode)!;
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Automatizaciones operativas</CardTitle>
        <CardDescription>{current.detail}</CardDescription>
        <CardAction>
          <DataProvenanceBadge status="demo" compact tooltip="Las reglas y el modo operativo no se guardan: el backend no tiene motor de automatizaciones." />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 xl:flex-row xl:items-center">
        <ul className="grid min-w-0 flex-1 gap-2 sm:grid-cols-2 xl:grid-cols-3 min-[106.25rem]:grid-cols-5">
          {DEMO_AUTOMATIONS.map((rule) => {
            const active = rule.activeIn.includes(mode);
            return (
              <li key={rule.key} className={cn("min-w-0 rounded-lg border p-2.5", active ? "border-primary/40 bg-primary/5" : "opacity-70")}>
                <p className="flex items-center gap-1.5 text-[13px] leading-tight font-medium">
                  <Bot className="size-4 shrink-0 text-primary" /> {rule.label}
                </p>
                <p className="mt-1 text-[11px] leading-tight text-muted-foreground">{rule.detail}</p>
                <LevelChip tone={active ? "ok" : "neutral"} className="mt-1.5">
                  {active ? "Activo" : "Inactivo"}
                </LevelChip>
              </li>
            );
          })}
        </ul>
        <div className="flex w-full flex-col gap-2 xl:w-56 xl:shrink-0">
          <label className="text-xs text-muted-foreground" htmlFor="operations-mode">
            Modo operativo
          </label>
          <select
            id="operations-mode"
            value={mode}
            onChange={(e) => onModeChange(e.target.value as OperatingMode)}
            className="rounded-md border bg-background px-2.5 py-1.5 text-sm"
          >
            {OPERATING_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <Button disabled title="Pendiente: no hay motor de reglas en el backend">
            <Settings2 /> Configurar reglas
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// --- Pipeline --------------------------------------------------------------------

export function statusTone(status: Order["status"]): LevelTone {
  if (status === "delivered") return "ok";
  if (status === "returned") return "bad";
  if (status === "in_transit" || status === "shipped") return "neutral";
  return "warn";
}

export function statusLabel(status: Order["status"]): string {
  return ORDER_STATUS_LABEL[status];
}

export const SLA_ICON = { ok: CheckCircle2, risk: Clock, breach: AlertTriangle } as const;
export const RETURNS_ICON = RotateCcw;
