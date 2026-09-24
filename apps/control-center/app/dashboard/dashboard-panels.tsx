"use client";

import Link from "next/link";
import { ArrowRight, Bot, ChevronRight, Landmark, Megaphone, Package, Rocket, Scale, ShoppingCart, Truck } from "lucide-react";
import type { ActivityRow, DecisionRow, OpportunityRow, SalesPoint } from "@/lib/dashboard-view";
import type { RequestKind, Severity } from "@/lib/demo/approvals";
import { relativeTime } from "@/lib/dates";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import type { Level, Risk } from "@/lib/research-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { LineChart } from "@/components/line-chart";
import { TEAM_ICON } from "@/components/team-icon";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

const ACTIVITY_TONE: Record<ActivityRow["state"], LevelTone> = {
  running: "ok",
  available: "neutral",
  waiting: "warn",
  offline: "bad",
};

const ACTIVITY_LABEL: Record<ActivityRow["state"], string> = {
  running: "Ejecutando",
  available: "Disponible",
  waiting: "En espera",
  offline: "Fuera de servicio",
};

const SEVERITY_TONE: Record<Severity, LevelTone> = { "Crítica": "bad", Alta: "warn", Media: "neutral", Baja: "neutral" };

const KIND_ICON: Record<RequestKind, typeof Package> = {
  marketing: Megaphone,
  suppliers: Truck,
  operations: Package,
  commerce: ShoppingCart,
  agents: Bot,
  legal: Scale,
  finance: Landmark,
};

const LEVEL_TONE: Record<Level, LevelTone> = { Alta: "ok", Media: "neutral", Baja: "warn" };
const RISK_TONE: Record<Risk, LevelTone> = { Bajo: "ok", Medio: "warn", Alto: "bad" };

/** Cuadrito con icono a la izquierda de cada fila, como en el mockup. */
function IconBox({ icon: Icon, className }: { icon: typeof Package; className?: string }) {
  return (
    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background/40", className)}>
      <Icon className="size-4 text-primary" />
    </span>
  );
}

function SeeAll({ href, label }: { href: string; label: string }) {
  return (
    <Button size="sm" variant="ghost" nativeButton={false} render={<Link href={href} />}>
      {label} <ArrowRight />
    </Button>
  );
}

// --- Actividad empresarial ----------------------------------------------------------

export function ActivityCard({ rows, usingDemoRuns, now }: { rows: ActivityRow[]; usingDemoRuns: boolean; now: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Actividad empresarial</CardTitle>
        <CardAction>
          <SeeAll href="/agents" label="Ver todos los agentes" />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {rows.length === 0 ? (
          <EmptyState icon={Bot} title="Sin agentes registrados" description="La actividad aparecerá en cuanto haya agentes en el registro." />
        ) : (
          <div className="overflow-x-auto">
            <Table className="[&_td]:px-2 [&_td]:py-2">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Agente</TableHead>
                  <TableHead>Última actividad</TableHead>
                  <TableHead className="text-right">Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <IconBox icon={TEAM_ICON[row.team] ?? Bot} />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{row.name}</span>
                          <span className="block truncate text-[11px] text-muted-foreground">{row.team}</span>
                        </span>
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <span className="block text-xs">
                        {row.currentTask ??
                          (row.runs > 0
                            ? `${formatInteger(row.runs)} ejecuciones · ${row.successRate === null ? "—" : formatPercent(row.successRate)} de éxito`
                            : "Sin ejecuciones registradas")}
                      </span>
                      <span className="block text-[11px] text-muted-foreground">
                        {row.lastActivityAt === null ? "Sin actividad" : relativeTime(row.lastActivityAt, now)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <LevelChip tone={ACTIVITY_TONE[row.state]}>{ACTIVITY_LABEL[row.state]}</LevelChip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          El agente, su estado y sus ejecuciones son reales; la tarea en curso es de demostración.
          {usingDemoRuns ? " El log de ejecuciones está vacío: se usan las mismas de demostración que en Agentes." : ""}
        </p>
      </CardContent>
    </Card>
  );
}

// --- Decisiones necesarias ----------------------------------------------------------

export function DecisionsCard({ rows, pending, now }: { rows: DecisionRow[]; pending: number; now: number }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Decisiones necesarias</CardTitle>
        <CardAction>
          <SeeAll href="/approvals" label="Ver todas" />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {rows.length === 0 ? (
          <EmptyState
            icon={Rocket}
            title="Nada esperando tu decisión"
            description="Las solicitudes que necesiten aprobación humana aparecerán aquí."
          />
        ) : (
          <ul className="divide-y">
            {rows.map((row) => (
              <li key={row.id} className="flex items-start gap-2.5 py-2.5 first:pt-0">
                <IconBox icon={KIND_ICON[row.kind] ?? Package} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{row.title}</p>
                  <p className="text-xs text-muted-foreground">{row.detail}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {row.kindLabel} · {relativeTime(row.requestedAt, now)}
                    {row.isDemo ? " · demostración" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <LevelChip tone={SEVERITY_TONE[row.severity]}>{row.severity}</LevelChip>
                  <Button size="icon" variant="ghost" nativeButton={false} render={<Link href="/approvals" aria-label={`Revisar: ${row.title}`} />}>
                    <ChevronRight />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-muted-foreground">
          {pending} pendiente{pending === 1 ? "" : "s"} en total. Se aprueban o rechazan en Aprobaciones; las de demostración no se
          pueden decidir.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Oportunidades ------------------------------------------------------------------

export function OpportunitiesCard({ rows }: { rows: OpportunityRow[] }) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Oportunidades</CardTitle>
        <CardAction>
          <SeeAll href="/research" label="Ver todas" />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        {rows.length === 0 ? (
          <EmptyState
            icon={Package}
            title="Todavía no hay catálogo"
            description="Las oportunidades salen de los productos investigados. Lanza un análisis de mercado en Investigación."
            action={
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                Ir a Investigación
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <Table className="[&_td]:px-2 [&_td]:py-2">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Producto</TableHead>
                  <TableHead>Demanda</TableHead>
                  <TableHead className="text-right">Margen</TableHead>
                  <TableHead>Riesgo</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.productId}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <IconBox icon={Package} />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium">{row.name}</span>
                          <span className="block truncate text-[11px] text-muted-foreground">{row.subcategory}</span>
                        </span>
                      </span>
                    </TableCell>
                    <TableCell>
                      <LevelChip tone={LEVEL_TONE[row.demand]}>{row.demand}</LevelChip>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="inline-flex items-center gap-1 tabular-nums">
                        {formatPercent(row.marginPct, 0)}
                        {row.marginIsReal ? null : (
                          <DataProvenanceBadge
                            status="demo"
                            compact
                            tooltip="Este producto no tiene análisis económico: el margen sale del modelo con los supuestos de demostración de Economía."
                          />
                        )}
                      </span>
                    </TableCell>
                    <TableCell>
                      <LevelChip tone={RISK_TONE[row.risk]}>{row.risk}</LevelChip>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs whitespace-nowrap text-muted-foreground">{row.stage}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">
          Productos reales del catálogo, ordenados por el mismo score de Investigación, con el margen del mismo modelo económico que
          Economía. La fase sale de hasta dónde ha llegado su pipeline de verdad; las señales de mercado son de demostración
          mientras no se lance un análisis.
        </p>
      </CardContent>
    </Card>
  );
}

// --- Ventas y margen ----------------------------------------------------------------

export function SalesMarginCard({
  points,
  days,
  onDaysChange,
  salesDelta,
}: {
  points: SalesPoint[];
  days: number;
  onDaysChange: (days: number) => void;
  salesDelta: number | null;
}) {
  const label = (at: number) => new Date(at).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });
  const atOf = (x: number) => points.find((point) => point.x === x)?.at ?? 0;
  const ticks = points.filter((_, index) => index % Math.max(1, Math.round(points.length / 5)) === 0).map((point) => point.x);

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Ventas / margen · últimos {days} días</CardTitle>
        <CardAction>
          <select
            value={days}
            onChange={(event) => onDaysChange(Number(event.target.value))}
            aria-label="Periodo"
            className="rounded-md border bg-background px-2 py-1 text-xs"
          >
            <option value={7}>Últimos 7 días</option>
            <option value={14}>Últimos 14 días</option>
            <option value={30}>Últimos 30 días</option>
          </select>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <LineChart
          series={[
            { key: "sales", label: "Ventas (€)", color: "var(--emerald)", points: points.map((p) => ({ x: p.x, y: p.sales })) },
            {
              key: "margin",
              label: "Margen (%)",
              color: "var(--text-secondary)",
              dashed: true,
              secondary: true,
              points: points.map((p) => ({ x: p.x, y: p.marginPct })),
            },
          ]}
          ariaLabel={`Ventas y margen de los últimos ${days} días`}
          formatY={(value) => formatInteger(value)}
          formatY2={(value) => formatPercent(value, 0)}
          formatX={(x) => label(atOf(x))}
          hoverTitle={(x) => label(atOf(x))}
          xTicks={ticks}
          dots={false}
          height={230}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 text-[11px] text-muted-foreground">
            {salesDelta === null
              ? "No hay periodo anterior con el que comparar."
              : `Las ventas ${salesDelta >= 0 ? "han aumentado" : "han bajado"} un ${formatPercent(Math.abs(salesDelta), 1)} respecto al mes anterior.`}
          </p>
          <SeeAll href="/cfo" label="Ver análisis" />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Modelo, no medición: AMAZONA no factura. El nivel es la parte de los ingresos mensuales del P&L de Finanzas que cubre la
          ventana, el reparto por día sigue a los pedidos de Operaciones y el margen de cada día aplica los costes variables y los
          operativos de ese mismo P&L. Total del periodo: {formatEuro(points.reduce((sum, point) => sum + point.sales, 0), 0)}.
        </p>
      </CardContent>
    </Card>
  );
}
