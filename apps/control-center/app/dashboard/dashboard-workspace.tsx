"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Bot, ClipboardCheck, Coins, Plus, ReceiptText, Scale } from "lucide-react";
import type {
  Agent,
  AgentExecution,
  Approval,
  PipelineReview,
  Product,
  RevenueEntriesPage,
  RevenueSeries,
  RevenueSummary,
} from "@/lib/api";
import { teamOf } from "@/lib/agents";
import { agentCards } from "@/lib/agents-view";
import { demoRequests, requestFromApproval, requestFromReview, type ApprovalRequest } from "@/lib/approvals-view";
import { activityRows, dashboardKpis, decisionRows, opportunityRows, type ProductDepth } from "@/lib/dashboard-view";
import { demoExecutions } from "@/lib/demo/agents";
import { buildBaseline } from "@/lib/economics-baseline";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { evaluate } from "@/lib/economics-model";
import { formatInteger, formatPercent } from "@/lib/format";
import { type RevenueWindow } from "@/lib/revenue-query";
import { periodLabel, revenueKpis, type KpiText, type Settled } from "@/lib/revenue-view";
import { buildRows } from "@/lib/research-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { HeaderClock } from "@/components/header-clock";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import type { DashboardProductData } from "./page";
import { DASHBOARD_DESCRIPTION, DASHBOARD_TITLE } from "./copy";
import { ActivityCard, DecisionsCard, OpportunitiesCard } from "./dashboard-panels";
import {
  OutsideVerifiedCard,
  PeriodSelect,
  RevenueBreakdownCard,
  RevenueEntriesCard,
  RevenueSeriesCard,
} from "./revenue-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: la tarea en curso de cada agente, las solicitudes de decisión que no vienen del backend y las señales de mercado de las oportunidades. Del backend: los ingresos (de su registro de hechos de pago verificados), los productos del catálogo y sus análisis, los agentes registrados con su estado, el log de ejecuciones y las aprobaciones y revisiones de pipeline pendientes. El Panel ya no enseña ventas ni beneficio modelados: el margen y el beneficio esperan a una fuente que el backend pueda demostrar (Finanzas).";

/** Qué demuestra el backend detrás de las cifras de ingresos, y qué NO demuestra. */
const LEDGER_TOOLTIP =
  "Hechos de pago verificados y registrados por el backend (ADR 0030): no es un modelo ni una estimación. No dice si la operación fue simulada — el registro todavía no guarda esa procedencia.";

const ACTIVITY_LIMIT = 5;
const DECISION_LIMIT = 4;
const OPPORTUNITY_LIMIT = 5;

/** Barras de ejecuciones por día (los siete días de la tarjeta de agentes). */
function RunBars({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  return (
    <span className="flex h-7 shrink-0 items-end gap-0.5" aria-hidden>
      {values.map((value, index) => (
        <span key={index} className="w-1.5 rounded-sm bg-primary" style={{ height: `${Math.max(8, (value / max) * 100)}%` }} />
      ))}
    </span>
  );
}

const iconBox = (icon: React.ReactNode) => (
  <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40">{icon}</span>
);

/** Una cifra de ingresos: el valor y su pie salen tal cual de `lib/revenue-view.ts`; si la lectura falló, se dice. */
function RevenueKpi({
  label,
  icon,
  summary,
  pick,
  tooltip,
  accent = false,
  tone = "default",
}: {
  label: string;
  icon: React.ReactNode;
  summary: Settled<RevenueSummary>;
  pick: (kpis: ReturnType<typeof revenueKpis>) => KpiText;
  tooltip: string;
  accent?: boolean;
  tone?: "default" | "warning";
}) {
  if (!summary.ok) {
    return <KpiCard label={label} value="No disponible" leading={iconBox(icon)} caption={summary.message} tone="danger" />;
  }
  const text = pick(revenueKpis(summary.data));
  return (
    <KpiCard
      label={label}
      value={text.value}
      leading={iconBox(icon)}
      caption={text.caption}
      accent={accent && !text.isNoData}
      tone={tone}
      provenance="ledger"
      provenanceCompact
      provenanceTooltip={tooltip}
    />
  );
}

export function DashboardWorkspace({
  data,
  products,
  agents,
  executions,
  approvals,
  reviews,
  now,
  days,
  revenue,
}: {
  data: DashboardProductData[];
  products: Product[];
  agents: Agent[];
  executions: AgentExecution[];
  approvals: Approval[];
  reviews: PipelineReview[];
  now: number;
  /** Periodo de los ingresos (7, 14 o 30 días): lo elige la URL y lo lee el servidor. */
  days: number;
  revenue: {
    window: RevenueWindow;
    summary: Settled<RevenueSummary>;
    series: Settled<RevenueSeries>;
    entries: Settled<RevenueEntriesPage>;
  };
}) {
  // Mismo criterio que Agentes: si el log está vacío se usan las ejecuciones de
  // demostración, para que las dos pantallas cuenten lo mismo.
  const usingDemoRuns = executions.length === 0;
  const runs = useMemo(
    () => (usingDemoRuns ? demoExecutions(agents, teamOf, now, 7) : executions),
    [agents, executions, usingDemoRuns, now],
  );
  const cards = useMemo(() => agentCards(agents, runs, now), [agents, runs, now]);

  // Mismas solicitudes que Aprobaciones: las reales primero y las de
  // demostración sobre el producto más avanzado.
  const best = useMemo(() => [...data].sort((a, b) => b.depth - a.depth)[0], [data]);
  const requests = useMemo<ApprovalRequest[]>(
    () => [
      ...approvals.map((approval) => requestFromApproval(approval, now)),
      ...reviews.map((review) => requestFromReview(review, now)),
      ...demoRequests(best, agents, now),
    ],
    [approvals, reviews, best, agents, now],
  );

  // El margen es el mismo que enseña Economía: el del modelo sobre los supuestos
  // del producto (cotización real o la que recomienda Proveedores, y el último
  // análisis económico). Es una ESTIMACIÓN del modelo, no un margen medido.
  const depths = useMemo<ProductDepth[]>(
    () =>
      data.map(({ product, quotes, economics, legal, storefronts, campaigns }) => {
        const analysis = economics[0];
        const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
        const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
        return {
          productId: product.id,
          quotes: quotes.length,
          economics: economics.length,
          legal: legal.length,
          storefronts: storefronts.length,
          campaigns: campaigns.length,
          marginPct: evaluate(buildBaseline(quote, analysis).inputs).contributionMargin,
          marginIsReal: economics.length > 0,
        };
      }),
    [data],
  );

  const kpis = useMemo(() => dashboardKpis({ agents, requests }), [agents, requests]);
  const research = useMemo(() => buildRows(products, []), [products]);
  const opportunities = useMemo(() => opportunityRows(research, depths, OPPORTUNITY_LIMIT), [research, depths]);
  const activity = useMemo(() => activityRows(cards, ACTIVITY_LIMIT), [cards]);
  const decisions = useMemo(() => decisionRows(requests, DECISION_LIMIT), [requests]);
  const runsPerDay = useMemo(() => {
    const dayStart = now - (now % 86_400_000);
    return Array.from({ length: 7 }, (_, index) => {
      const from = dayStart - (6 - index) * 86_400_000;
      return runs.filter((run) => {
        const at = new Date(`${run.created_at}${/[zZ]|[+-]\d{2}:?\d{2}$/.test(run.created_at) ? "" : "Z"}`).getTime();
        return at >= from && at < from + 86_400_000;
      }).length;
    });
  }, [runs, now]);

  const period = periodLabel(days);

  return (
    <div className="space-y-4">
      <PageHeader
        title={DASHBOARD_TITLE}
        description={DASHBOARD_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="ledger" tooltip={LEDGER_TOOLTIP} />
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <PeriodSelect days={days} />
            <HeaderClock />
            <Button nativeButton={false} render={<Link href="/ceo" />}>
              <Plus /> Nuevo objetivo
            </Button>
          </>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Indicadores del negocio">
        <RevenueKpi
          label={`Ingresos verificados · ${period}`}
          icon={<Coins className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.verified}
          accent
          tooltip="Cobros verificados del registro de ingresos, en EUR (la única moneda consolidada). Otras monedas se enseñan aparte y nunca se suman. Sin entradas en EUR el valor es «Sin datos», no 0."
        />
        <RevenueKpi
          label={`En revisión · ${period}`}
          icon={<Scale className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.underReview}
          tone="warning"
          tooltip="Dinero recibido como duplicado o con discrepancia y aún sin resolver, en EUR. No suma a lo verificado ni se compensa con ello."
        />
        <RevenueKpi
          label={`Evidencia pendiente · ${period}`}
          icon={<ReceiptText className="size-5 text-primary" />}
          summary={revenue.summary}
          pick={(k) => k.pending}
          tooltip="Eventos de pago (cobros o reembolsos) que no se pudieron asentar. No son ingreso ni reembolso y no entran en ningún total."
        />
        <KpiCard
          label="Agentes en línea"
          value={`${kpis.agentsOnline} / ${kpis.agentsTotal}`}
          leading={iconBox(<Bot className="size-5 text-primary" />)}
          trailing={<RunBars values={runsPerDay} />}
          caption={`${formatPercent(kpis.agentsRatio, 0)} operativos`}
          provenance="verified"
          provenanceCompact
          provenanceTooltip="Agentes del registro que no están fuera de servicio. Las barras son sus ejecuciones de los últimos siete días."
        />
        <KpiCard
          label="Aprobaciones pendientes"
          value={formatInteger(kpis.pendingDecisions)}
          leading={iconBox(<ClipboardCheck className="size-5 text-primary" />)}
          tone={kpis.pendingDecisions > 0 ? "warning" : "default"}
          caption={
            kpis.realDecisions > 0
              ? `${kpis.realDecisions} del backend · ${kpis.pendingDecisions - kpis.realDecisions} de demostración`
              : "Requieren una decisión"
          }
          footer={
            <Button size="sm" variant="ghost" nativeButton={false} render={<Link href="/approvals" />}>
              Revisar
            </Button>
          }
          provenance={kpis.realDecisions === kpis.pendingDecisions ? "verified" : "demo"}
          provenanceCompact
          provenanceTooltip="Solicitudes pendientes de decisión: las del backend (aprobaciones y revisiones de pipeline) más las de demostración de Aprobaciones."
        />
      </section>

      <section className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-12" aria-label="Actividad y decisiones">
        <div className="min-w-0 2xl:col-span-7">
          <ActivityCard rows={activity} usingDemoRuns={usingDemoRuns} now={now} />
        </div>
        <div className="min-w-0 2xl:col-span-5">
          <DecisionsCard rows={decisions} pending={kpis.pendingDecisions} now={now} />
        </div>
      </section>

      <section className="grid gap-3 lg:grid-cols-2" aria-label="Oportunidades e ingresos por día">
        <OpportunitiesCard rows={opportunities} />
        <RevenueSeriesCard key={revenue.window.from} series={revenue.series} window={revenue.window} days={days} />
      </section>

      <section className="grid gap-3 lg:grid-cols-2" aria-label="Ingresos por moneda y dinero fuera de lo verificado">
        <RevenueBreakdownCard summary={revenue.summary} days={days} />
        <OutsideVerifiedCard summary={revenue.summary} days={days} />
      </section>

      <section aria-label="Entradas del registro de ingresos">
        <RevenueEntriesCard key={revenue.window.from} initial={revenue.entries} window={revenue.window} days={days} />
      </section>
    </div>
  );
}
