"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Bot, ClipboardCheck, Coins, Plus, Wallet } from "lucide-react";
import type { Agent, AgentExecution, Approval, PipelineReview, Product, SupplierQuote } from "@/lib/api";
import { teamOf } from "@/lib/agents";
import { agentCards } from "@/lib/agents-view";
import { demoRequests, requestFromApproval, requestFromReview, type ApprovalRequest } from "@/lib/approvals-view";
import { buildPnl, monthFactor, scalePnl, withDeltas, type ProductFinance } from "@/lib/cfo-view";
import {
  activityRows,
  dashboardKpis,
  decisionRows,
  opportunityRows,
  salesSeries,
  type ProductDepth,
} from "@/lib/dashboard-view";
import { demoExecutions } from "@/lib/demo/agents";
import { DEMO_SALE } from "@/lib/demo/economics";
import { demoQuotes } from "@/lib/demo/sourcing";
import { demoSku } from "@/lib/demo/storefront";
import { buildBaseline } from "@/lib/economics-baseline";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { evaluate } from "@/lib/economics-model";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { buildOrders, type ProductInput, type SupplierInput } from "@/lib/operations-view";
import { buildRows } from "@/lib/research-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { HeaderClock } from "@/components/header-clock";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Sparkline } from "@/components/sparkline";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DashboardProductData } from "./page";
import { DASHBOARD_DESCRIPTION, DASHBOARD_TITLE } from "./copy";
import { ActivityCard, DecisionsCard, OpportunitiesCard, SalesMarginCard } from "./dashboard-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: AMAZONA no factura, no recibe pedidos ni tiene contabilidad, así que las ventas, el beneficio y la serie de 30 días son el modelo de Finanzas y Operaciones, no una medición. La tarea en curso de cada agente y las solicitudes de decisión que no vienen del backend también lo son. Real: los productos del catálogo y sus análisis (de ahí salen el margen y la fase de cada oportunidad), los agentes registrados con su estado, el log de ejecuciones y las aprobaciones y revisiones de pipeline pendientes.";

const PERIODS = [7, 14, 30];
const ACTIVITY_LIMIT = 5;
const DECISION_LIMIT = 4;
const OPPORTUNITY_LIMIT = 5;

function quoteToSupplier(quote: SupplierQuote, isDemo: boolean): SupplierInput {
  return {
    id: quote.supplier_id,
    name: quote.data?.name ?? quote.supplier_id,
    region: quote.data?.region ?? "eu",
    leadTimeDays: quote.lead_time_days,
    reliability: quote.reliability_score,
    verified: quote.verified,
    isDemo,
  };
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-muted-foreground">Sin periodo anterior</span>;
  const Icon = value >= 0 ? ArrowUp : ArrowDown;
  return (
    <span className={cn("flex items-center gap-1 text-xs", value >= 0 ? "text-primary" : "text-warning")}>
      <Icon className="size-3 shrink-0" />
      {value >= 0 ? "+" : "−"}
      {formatPercent(Math.abs(value), 1)}
    </span>
  );
}

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

export function DashboardWorkspace({
  data,
  products,
  agents,
  executions,
  approvals,
  reviews,
  now,
  today,
}: {
  data: DashboardProductData[];
  products: Product[];
  agents: Agent[];
  executions: AgentExecution[];
  approvals: Approval[];
  reviews: PipelineReview[];
  now: number;
  today: string;
}) {
  const [days, setDays] = useState(() => {
    if (typeof window === "undefined") return 30;
    const value = Number(new URLSearchParams(window.location.search).get("dias"));
    return PERIODS.includes(value) ? value : 30;
  });

  // El periodo del gráfico sobrevive a una recarga sin volver al servidor.
  const changeDays = useCallback((value: number) => {
    setDays(value);
    const url = new URL(window.location.href);
    url.searchParams.set("dias", String(value));
    window.history.replaceState(null, "", url);
  }, []);

  // Mismos supuestos que Economía y Finanzas: cotización real (o la que
  // recomienda Proveedores) y último análisis económico de cada producto.
  const finances = useMemo<ProductFinance[]>(
    () =>
      data.map(({ product, economics, quotes }) => {
        const analysis = economics[0];
        const options = dedupeQuotesBySupplier(quotes, analysis?.supplier_quote_id);
        const quote = options.find((q) => q.id === analysis?.supplier_quote_id) ?? options[0];
        return {
          id: product.id,
          name: product.name,
          category: product.category,
          inputs: buildBaseline(quote, analysis).inputs,
          analysis,
          isDemo: !analysis,
        };
      }),
    [data],
  );

  // Los mismos pedidos que Operaciones y Finanzas.
  const orderProducts = useMemo<ProductInput[]>(
    () =>
      data.map(({ product, economics, quotes }) => {
        const real = quotes.length > 0;
        const ranked = rankSuppliers(real ? dedupeQuotesBySupplier(quotes) : demoQuotes(product.id));
        return {
          id: product.id,
          name: product.name,
          sku: demoSku(product.category, product.id),
          price: economics[0]?.sale_price ?? DEMO_SALE.salePrice,
          suppliers: ranked.slice(0, 3).map((r) => quoteToSupplier(r.quote, !real)),
        };
      }),
    [data],
  );

  const orders = useMemo(() => buildOrders(orderProducts, today), [orderProducts, today]);
  const basePnl = useMemo(() => buildPnl(finances), [finances]);
  const previousPnl = useMemo(() => scalePnl(basePnl, monthFactor(-1, "revenue"), monthFactor(-1, "costs")), [basePnl]);
  const pnl = useMemo(
    () => withDeltas(scalePnl(basePnl, monthFactor(0, "revenue"), monthFactor(0, "costs")), previousPnl),
    [basePnl, previousPnl],
  );

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
  // del producto, no el `margin_percent` del análisis (que ninguna otra pantalla usa).
  const depths = useMemo<ProductDepth[]>(
    () =>
      data.map(({ product, quotes, economics, legal, storefronts, campaigns }, index) => ({
        productId: product.id,
        quotes: quotes.length,
        economics: economics.length,
        legal: legal.length,
        storefronts: storefronts.length,
        campaigns: campaigns.length,
        marginPct: finances[index] ? evaluate(finances[index].inputs).contributionMargin : null,
        marginIsReal: economics.length > 0,
      })),
    [data, finances],
  );

  const kpis = useMemo(() => dashboardKpis({ pnl, previousPnl, agents, requests }), [pnl, previousPnl, agents, requests]);
  const series = useMemo(() => salesSeries(orders, pnl, today, days), [orders, pnl, today, days]);
  const monthSeries = useMemo(() => salesSeries(orders, pnl, today, 30), [orders, pnl, today]);
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

  return (
    <div className="space-y-4">
      <PageHeader
        title={DASHBOARD_TITLE}
        description={DASHBOARD_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <HeaderClock />
            <Button nativeButton={false} render={<Link href="/ceo" />}>
              <Plus /> Nuevo objetivo
            </Button>
          </>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Indicadores del negocio">
        <KpiCard
          label="Ventas"
          value={formatEuro(kpis.sales, 0)}
          leading={<span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40"><Coins className="size-5 text-primary" /></span>}
          trailing={<Sparkline values={monthSeries.map((point) => point.sales)} width={72} height={30} />}
          accent
          footer={<Delta value={kpis.salesDelta} />}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="Ingresos del mes del mismo P&L que Finanzas, calculado sobre los análisis económicos reales de cada producto. AMAZONA no factura: es un modelo, no una medición."
        />
        <KpiCard
          label="Beneficio estimado"
          value={formatEuro(kpis.profit, 0)}
          leading={<span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40"><Wallet className="size-5 text-primary" /></span>}
          trailing={<Sparkline values={monthSeries.map((point) => point.sales * point.marginPct)} width={72} height={30} />}
          accent
          footer={<Delta value={kpis.profitDelta} />}
          provenance="demo"
          provenanceCompact
          provenanceTooltip="Beneficio neto del mismo P&L que Finanzas, después de costes e impuestos simulados."
        />
        <KpiCard
          label="Agentes en línea"
          value={`${kpis.agentsOnline} / ${kpis.agentsTotal}`}
          leading={<span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40"><Bot className="size-5 text-primary" /></span>}
          trailing={<RunBars values={runsPerDay} />}
          caption={`${formatPercent(kpis.agentsRatio, 0)} operativos`}
          provenance="verified"
          provenanceCompact
          provenanceTooltip="Agentes del registro que no están fuera de servicio. Las barras son sus ejecuciones de los últimos siete días."
        />
        <KpiCard
          label="Aprobaciones pendientes"
          value={formatInteger(kpis.pendingDecisions)}
          leading={<span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background/40"><ClipboardCheck className="size-5 text-primary" /></span>}
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

      <section className="grid gap-3 lg:grid-cols-2" aria-label="Oportunidades y ventas">
        <OpportunitiesCard rows={opportunities} />
        <SalesMarginCard points={series} days={days} onDaysChange={changeDays} salesDelta={kpis.salesDelta} />
      </section>
    </div>
  );
}
