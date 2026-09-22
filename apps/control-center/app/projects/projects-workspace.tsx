"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Ban,
  Box,
  FolderKanban,
  FlaskConical,
  Gauge,
  Layers,
  PackageSearch,
  Plus,
  Rocket,
  Settings2,
  TrendingUp,
  Truck,
  Wallet,
} from "lucide-react";
import type { Agent, AuditEntry } from "@/lib/api";
import { DEMO_SALE, DEMO_UNIT_COSTS } from "@/lib/demo/economics";
import { DEMO_RETURN_RATE } from "@/lib/demo/operations";
import { demoQuotes } from "@/lib/demo/sourcing";
import { demoSku } from "@/lib/demo/storefront";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { buildBaseline } from "@/lib/economics-baseline";
import { evaluate } from "@/lib/economics-model";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { acquisitionPlan, planTotal } from "@/lib/marketing-view";
import { MARKET_LABELS, marketLabel } from "@/lib/markets";
import { buildOrders, startOfDay, type Order, type ProductInput, type SupplierInput } from "@/lib/operations-view";
import { DECISION_VERDICT, pipelineSteps, projectedFinance, taskProgress } from "@/lib/projects";
import {
  PHASES,
  PORTFOLIO_TABS,
  demoProjects,
  filterProjects,
  learnings,
  nextDecision,
  phaseDistribution,
  plannedVsActual,
  portfolioCounts,
  profitByMarket,
  projectFromProduct,
  projectMilestones,
  projectRisks,
  type PortfolioTab,
  type ProjectCard,
  type ProjectPhase,
} from "@/lib/projects-view";
import { categoryLabel } from "@/lib/research-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DonutChart } from "@/components/donut-chart";
import { EmptyState } from "@/components/empty-state";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { PageHeader } from "@/components/page-header";
import { RankedBars } from "@/components/ranked-bars";
import { RingGauge } from "@/components/ring-gauge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import type { BackendProject, ProductProjectData } from "./page";
import { PROJECTS_DESCRIPTION, PROJECTS_TITLE } from "./copy";
import {
  ActivityCard,
  AgentsCard,
  DocumentsCard,
  KeyMetricsCard,
  LearningsCard,
  MilestonesCard,
  NextDecisionCard,
  PipelineStepper,
  PlannedVsActualCard,
  ProjectFinanceCard,
  RisksCard,
  formatDay,
  type KeyMetric,
} from "./projects-panels";

const DEMO_TOOLTIP =
  "Incluye datos de demostración: un proyecto del backend es un grafo de tareas del Director ejecutivo sin producto, mercado, fase de negocio, salud ni beneficio, así que la cartera se construye presentando cada producto real como un proyecto y se completa con proyectos de ejemplo. Real: el score de Investigación, el proveedor, el análisis económico y legal, la tienda, la campaña, la simulación de operaciones, la actividad de auditoría y los agentes registrados. El beneficio real y los pedidos vienen de los pedidos de demostración de Operaciones.";

const STATUS_TONE: Record<ProjectCard["status"], LevelTone> = {
  "En curso": "ok",
  "En riesgo": "warn",
  Bloqueado: "bad",
  Pausado: "neutral",
  Cerrado: "neutral",
};

const DETAIL_TABS = [
  { key: "resumen", label: "Resumen" },
  { key: "pipeline", label: "Pipeline" },
  { key: "hitos", label: "Hitos" },
  { key: "metricas", label: "Métricas" },
  { key: "finanzas", label: "Finanzas" },
  { key: "documentos", label: "Documentos" },
  { key: "actividad", label: "Actividad" },
] as const;

type DetailTab = (typeof DETAIL_TABS)[number]["key"];

const INPUT_CLASS = "min-w-0 rounded-md border bg-background px-2.5 py-1.5 text-xs";

/** Guarda la selección en la URL sin recargar el servidor. */
function syncUrl(id: string) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("proyecto", id);
  window.history.replaceState(null, "", url);
}

function quoteToSupplier(quote: { supplier_id: string; lead_time_days: number; reliability_score: number; verified: boolean; data: { name?: string; region?: string } | null }, isDemo: boolean): SupplierInput {
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

export function ProjectsWorkspace({
  productData,
  backend,
  audit,
  agents,
  today,
  initialSelection,
}: {
  productData: ProductProjectData[];
  backend: BackendProject[];
  audit: AuditEntry[];
  agents: Agent[];
  today: string;
  initialSelection?: string;
}) {
  const [tab, setTab] = useState<PortfolioTab>("all");
  const [query, setQuery] = useState("");
  const [market, setMarket] = useState("all");
  const [category, setCategory] = useState("all");
  const [status, setStatus] = useState("all");
  const [detailTab, setDetailTab] = useState<DetailTab>("resumen");
  const [selectedId, setSelectedId] = useState<string | null>(initialSelection ?? null);

  const now = startOfDay(today);

  // Pedidos de Operaciones: el beneficio real y el capital expuesto de cada proyecto.
  const orderProducts = useMemo<ProductInput[]>(
    () =>
      productData.map(({ product, data }) => {
        const real = data.quotes.length > 0;
        const ranked = rankSuppliers(real ? dedupeQuotesBySupplier(data.quotes) : demoQuotes(product.id));
        return {
          id: product.id,
          name: product.name,
          sku: demoSku(product.category, product.id),
          price: data.economics[0]?.sale_price ?? DEMO_SALE.salePrice,
          suppliers: ranked.slice(0, 3).map((r) => quoteToSupplier(r.quote, !real)),
        };
      }),
    [productData],
  );
  const orders = useMemo(() => buildOrders(orderProducts, today), [orderProducts, today]);

  const auditByProduct = useMemo(() => {
    const map = new Map<string, AuditEntry[]>();
    for (const { product, data } of productData) {
      const ids = new Set(
        [...data.economics, ...data.legal, ...data.storefronts, ...data.listings, ...data.campaigns, ...data.operations].map((r) => r.correlation_id),
      );
      map.set(
        product.id,
        audit.filter((entry) => ids.has(entry.correlation_id) || entry.resource.includes(product.id)),
      );
    }
    return map;
  }, [productData, audit]);

  const projects = useMemo<ProjectCard[]>(() => {
    const fromProducts = productData.map(({ product, data }, index) =>
      projectFromProduct(
        {
          product,
          quotes: data.quotes,
          economics: data.economics,
          legal: data.legal,
          storefronts: data.storefronts,
          campaigns: data.campaigns,
          operations: data.operations,
          orders: orders.filter((o) => o.productId === product.id),
          audit: auditByProduct.get(product.id) ?? [],
          market: data.storefronts[0]?.market ?? data.legal[0]?.market ?? "eu",
        },
        index,
        now,
      ),
    );
    const fromBackend: ProjectCard[] = backend.map((item, index) => {
      const steps = pipelineSteps(item.tasks, item.decision);
      const progress = taskProgress(item.tasks);
      const finance = projectedFinance(item.decision);
      const phases: ProjectPhase[] = PHASES.map((meta, k) => {
        const step = steps[k];
        if (!step) return { ...meta, state: "todo" as const, detail: "Sin enlazar", score: null };
        return { ...meta, state: step.state, detail: step.recommendation ?? (step.state === "done" ? "Completado" : "Pendiente"), score: null };
      });
      return {
        id: item.project.id,
        code: `CEO-${String(index + 1).padStart(4, "0")}`,
        name: item.project.name,
        category: "—",
        market: "eu",
        phases,
        phase: phases.find((p) => p.state === "current")?.key ?? "research",
        phaseLabel: item.decision ? DECISION_VERDICT[item.decision.status].title : "En validación",
        status: item.decision?.status === "NO_GO" ? "Bloqueado" : "En curso",
        health: Math.round((item.decision?.confidence ?? 0) * 100),
        progress: progress.ratio,
        projectedProfit: finance?.monthlyProfit ?? null,
        realProfit: null,
        capitalExposed: 0,
        startedAt: now,
        isDemo: false,
      } satisfies ProjectCard;
    });
    return [...fromProducts, ...fromBackend, ...demoProjects(now, 24 - productData.length)];
  }, [productData, backend, orders, auditByProduct, now]);

  const counts = portfolioCounts(projects);
  const visible = filterProjects(projects, { tab, query, market, category, status });
  const selected = projects.find((p) => p.id === selectedId || p.code === selectedId) ?? visible[0] ?? projects[0];

  if (projects.length === 0) {
    return (
      <div>
        <PageHeader title={PROJECTS_TITLE} description={PROJECTS_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay cartera"
              description="Cada producto investigado se convierte en un proyecto: empieza por Investigación."
              action={
                <Button size="sm" variant="outline" nativeButton={false} render={<Link href="/research" />}>
                  Ir a Investigación
                </Button>
              }
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  // Datos del proyecto seleccionado (si viene de un producto real).
  const source = productData.find((item) => item.product.id === selected.productId);
  const analysis = source?.data.economics[0];
  const quoteOptions = source ? dedupeQuotesBySupplier(source.data.quotes, analysis?.supplier_quote_id) : [];
  const quote = quoteOptions.find((q) => q.id === analysis?.supplier_quote_id) ?? quoteOptions[0];
  const baseline = buildBaseline(quote, analysis);
  const economics = evaluate(baseline.inputs);
  const selectedOrders: Order[] = selected.productId ? orders.filter((o) => o.productId === selected.productId) : [];
  const campaign = source?.data.campaigns[0];
  const marketingPlan = acquisitionPlan(campaign ? [campaign] : [], Math.round(baseline.inputs.monthlyOrders * baseline.inputs.cac));
  const selectedAudit = selected.productId ? (auditByProduct.get(selected.productId) ?? []) : [];

  const decision = nextDecision(selected, {
    maxCac: source ? Math.round(economics.maxCac * 100) / 100 : null,
    amount: source ? planTotal(marketingPlan) : null,
  });

  const researchPhase = selected.phases.find((p) => p.key === "research")!;
  const metrics: KeyMetric[] = [
    { key: "research", label: "Investigación", value: researchPhase.score !== null ? `${researchPhase.score}/100` : "—", detail: "Score de oportunidad", tone: "ok", href: "/research" },
    {
      key: "economics",
      label: "Economía",
      value: source ? formatPercent(economics.contributionMargin) : "—",
      detail: "Margen de contribución",
      tone: economics.contributionMargin >= 0.3 ? "ok" : "warn",
      href: "/economics",
    },
    {
      key: "marketing",
      label: "Marketing",
      value: source ? `CAC ${formatEuro(baseline.inputs.cac)}` : "—",
      detail: source ? `ROAS ${(baseline.inputs.salePrice / baseline.inputs.cac).toLocaleString("es-ES", { maximumFractionDigits: 2 })} x` : "Sin datos",
      tone: "ok",
      href: "/marketing",
    },
    {
      key: "operations",
      label: "Operaciones",
      value: selectedOrders.length > 0 ? formatInteger(selectedOrders.length) : "—",
      detail: selectedOrders.length > 0 ? "Pedidos en 30 días" : "Pendiente",
      tone: selectedOrders.length > 0 ? "ok" : "muted",
      href: "/operations",
    },
  ];

  const comparison = plannedVsActual({
    projectId: selected.id,
    plannedOrders: baseline.inputs.monthlyOrders,
    plannedRevenue: baseline.inputs.salePrice * baseline.inputs.monthlyOrders,
    plannedCac: baseline.inputs.cac,
    plannedMargin: economics.contributionMargin,
    plannedReturnRate: DEMO_RETURN_RATE,
    plannedDeliveryDays: DEMO_UNIT_COSTS.conversionPct > 0 ? 4 : 4,
    orders: selectedOrders,
    today: now,
  });

  // Política de capital de la demostración: como mucho un mes de compras al proveedor.
  const capitalLimit = Math.round((baseline.inputs.supplierCost + baseline.inputs.transport + baseline.inputs.tariff) * baseline.inputs.monthlyOrders);
  const risks = projectRisks({
    analyses: [
      { source: "Economía", risks: analysis?.data?.risks ?? [] },
      { source: "Legal", risks: source?.data.legal[0]?.data?.risks ?? [] },
      { source: "Marketing", risks: campaign?.data?.risks ?? [] },
      { source: "Operaciones", risks: source?.data.operations[0]?.data?.risks ?? [] },
    ].filter((entry) => entry.risks.length > 0),
    project: selected,
    capitalExposed: selected.capitalExposed,
    capitalLimit,
  });

  function selectProject(id: string) {
    setSelectedId(id);
    setDetailTab("resumen");
    syncUrl(id);
  }

  const distribution = phaseDistribution(projects);
  const markets = profitByMarket(projects);
  const categories = [...new Set(projects.map((p) => p.category))].filter((c) => c !== "—");

  return (
    <div className="space-y-5">
      <PageHeader
        title={PROJECTS_TITLE}
        description={PROJECTS_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge status="demo" tooltip={DEMO_TOOLTIP} />
            <Button nativeButton={false} render={<Link href="/ceo" />}>
              <Plus /> Nuevo objetivo / proyecto
            </Button>
          </>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.25fr)]">
        {/* Cartera */}
        <div className="min-w-0 space-y-4">
          <section className="grid grid-cols-2 gap-2.5 sm:grid-cols-4" aria-label="Resumen de la cartera">
            {[
              { key: "active", label: "Activos", value: formatInteger(counts.active), icon: FolderKanban, tone: "" },
              { key: "validation", label: "Validación", value: formatInteger(counts.validation), icon: FlaskConical, tone: "" },
              { key: "launch", label: "Lanzamiento", value: formatInteger(counts.launch), icon: Rocket, tone: "" },
              { key: "operating", label: "Operativos", value: formatInteger(counts.operating), icon: Settings2, tone: "" },
              { key: "risk", label: "En riesgo", value: formatInteger(counts.atRisk), icon: AlertTriangle, tone: "text-warning" },
              { key: "blocked", label: "Bloqueado", value: formatInteger(counts.blocked), icon: Ban, tone: "text-destructive" },
              { key: "projected", label: "Beneficio previsto", value: `${formatEuro(counts.projectedProfit, 0)}`, icon: Gauge, tone: "text-primary" },
              { key: "real", label: "Beneficio real", value: `${formatEuro(counts.realProfit, 0)}`, icon: TrendingUp, tone: "text-primary" },
            ].map((item) => (
              <Card key={item.key} className="min-w-0 gap-0 py-3">
                <CardContent className="flex items-center gap-2.5 px-3">
                  <item.icon className={cn("size-5 shrink-0", item.tone || "text-primary")} />
                  <span className="min-w-0">
                    <span className={cn("block text-lg leading-tight font-semibold", item.tone)}>{item.value}</span>
                    <span className="block text-[11px] leading-tight text-muted-foreground">{item.label}</span>
                  </span>
                </CardContent>
              </Card>
            ))}
          </section>

          <Card className="min-w-0">
            <CardContent className="space-y-3">
              <Tabs value={tab} onValueChange={(v) => setTab(v as PortfolioTab)}>
                <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                  {PORTFOLIO_TABS.map((item) => (
                    <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                      {item.label} ({filterProjects(projects, { tab: item.key }).length})
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>

              <div className="flex flex-wrap gap-2">
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  type="search"
                  placeholder="Buscar proyecto…"
                  aria-label="Buscar proyecto"
                  className={cn(INPUT_CLASS, "flex-1")}
                />
                <select value={market} onChange={(e) => setMarket(e.target.value)} aria-label="Mercado" className={INPUT_CLASS}>
                  <option value="all">Mercado</option>
                  {Object.entries(MARKET_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Categoría" className={INPUT_CLASS}>
                  <option value="all">Categoría</option>
                  {categories.map((value) => (
                    <option key={value} value={value}>
                      {categoryLabel(value)}
                    </option>
                  ))}
                </select>
                <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Estado" className={INPUT_CLASS}>
                  <option value="all">Estado</option>
                  {["En curso", "En riesgo", "Bloqueado", "Pausado", "Cerrado"].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th className="pb-2 text-left font-normal">Proyecto</th>
                      <th className="pb-2 text-left font-normal">Producto</th>
                      <th className="pb-2 text-left font-normal">Fase</th>
                      <th className="pb-2 text-left font-normal">Salud</th>
                      <th className="pb-2 text-right font-normal">Progreso</th>
                      <th className="pb-2 text-right font-normal">Beneficio prev.</th>
                      <th className="pb-2 text-right font-normal">Inicio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((project) => (
                      <tr
                        key={project.id}
                        onClick={() => selectProject(project.id)}
                        aria-selected={project.id === selected.id}
                        className={cn("cursor-pointer border-t transition hover:bg-panel-hover", project.id === selected.id && "bg-primary/5")}
                      >
                        <td className="py-1.5 font-medium whitespace-nowrap">{project.code}</td>
                        <td className="py-1.5">
                          <span className="flex items-center gap-1.5">
                            <Box className="size-3.5 shrink-0 text-muted-foreground" />
                            <span className="leading-tight">{project.name}</span>
                          </span>
                        </td>
                        <td className="py-1.5">
                          <LevelChip tone={STATUS_TONE[project.status]}>{project.phaseLabel}</LevelChip>
                        </td>
                        <td className="py-1.5">
                          <span
                            className={cn(
                              "inline-block size-2.5 rounded-full",
                              project.health >= 75 ? "bg-primary" : project.health >= 50 ? "bg-warning" : "bg-destructive",
                            )}
                            aria-label={`Salud ${project.health}/100`}
                          />
                        </td>
                        <td className={cn("py-1.5 text-right tabular-nums", project.progress < 0.4 && "text-destructive")}>
                          {formatPercent(project.progress, 0)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {project.projectedProfit !== null ? `${formatEuro(project.projectedProfit, 0)}/mes` : "—"}
                        </td>
                        <td className="py-1.5 text-right whitespace-nowrap text-muted-foreground">{formatDay(project.startedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visible.length === 0 ? <p className="py-3 text-sm text-muted-foreground">Sin proyectos con estos filtros.</p> : null}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2">
            <Card className="min-w-0">
              <CardHeader>
                <CardTitle>Proyectos por fase</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-4">
                <DonutChart
                  ariaLabel="Proyectos por bloque de fases"
                  segments={distribution.map((d) => ({ key: d.key, value: d.value, color: d.color }))}
                  centerLabel={formatInteger(counts.active + counts.closed)}
                  centerCaption="Total"
                  size={116}
                />
                <ul className="min-w-28 flex-1 space-y-1.5 text-xs">
                  {distribution.map((item) => (
                    <li key={item.key} className="flex items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="size-2.5 shrink-0 rounded-full" style={{ background: item.color }} aria-hidden />
                        {item.label}
                      </span>
                      <span className="tabular-nums">{item.value}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            <Card className="min-w-0">
              <CardHeader>
                <CardTitle>Beneficio previsto por mercado</CardTitle>
              </CardHeader>
              <CardContent>
                <RankedBars
                  ariaLabel="Beneficio previsto por mercado"
                  items={markets.map((row) => ({ key: row.key, label: marketLabel(row.key), value: row.value, valueLabel: formatEuro(row.value, 0) }))}
                />
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Detalle */}
        <div className="min-w-0 space-y-4">
          <Card className="min-w-0">
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 gap-3">
                  <span className="flex size-14 shrink-0 items-center justify-center rounded-xl border bg-background/60 text-primary">
                    <Box className="size-7" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs text-primary">{selected.code}</p>
                    <p className="text-xl leading-tight font-semibold">{selected.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {marketLabel(selected.market)} · {selected.category === "—" ? "Sin categoría" : categoryLabel(selected.category)} · Envío directo
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <LevelChip tone={STATUS_TONE[selected.status]}>{selected.status}</LevelChip>
                  {selected.isDemo ? <DataProvenanceBadge status="demo" compact tooltip="Proyecto de ejemplo: no hay ningún producto detrás." /> : null}
                </div>
              </div>

              <Tabs value={detailTab} onValueChange={(v) => setDetailTab(v as DetailTab)}>
                <TabsList className="flex w-full flex-wrap justify-start group-data-horizontal/tabs:h-auto">
                  {DETAIL_TABS.map((item) => (
                    <TabsTrigger key={item.key} value={item.key} className="flex-none px-2.5 text-xs">
                      {item.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>

              <section className="grid grid-cols-2 gap-2.5 lg:grid-cols-5" aria-label="Indicadores del proyecto">
                <div className="flex min-w-0 items-center gap-2 rounded-xl border bg-background/40 p-2.5">
                  <RingGauge value={selected.health / 100} size={52} centerLabel={String(selected.health)} />
                  <span className="min-w-0">
                    <span className="block text-[11px] leading-tight text-muted-foreground">Project Health</span>
                    <span className="block text-sm font-semibold">{selected.health}/100</span>
                  </span>
                </div>
                {[
                  { label: "Fase actual", value: selected.phaseLabel, icon: Layers },
                  { label: "Progreso global", value: formatPercent(selected.progress, 0), icon: Rocket },
                  { label: "Beneficio previsto", value: selected.projectedProfit !== null ? `${formatEuro(selected.projectedProfit, 0)}/mes` : "—", icon: TrendingUp },
                  { label: "Capital expuesto", value: formatEuro(selected.capitalExposed, 0), icon: Wallet },
                ].map((item) => (
                  <div key={item.label} className="flex min-w-0 items-center gap-2 rounded-xl border bg-background/40 p-2.5">
                    <item.icon className="size-5 shrink-0 text-primary" />
                    <span className="min-w-0">
                      <span className="block text-[11px] leading-tight text-muted-foreground">{item.label}</span>
                      <span className="block text-[13px] leading-tight font-semibold break-words">{item.value}</span>
                    </span>
                  </div>
                ))}
              </section>

              <PipelineStepper phases={selected.phases} />
            </CardContent>
          </Card>

          {detailTab === "resumen" ? (
            <>
              <div className="grid gap-4 min-[106.25rem]:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)]">
                <NextDecisionCard decision={decision} />
                <div className="min-w-0 space-y-4">
                  <KeyMetricsCard metrics={metrics} />
                  <div className="grid gap-4 sm:grid-cols-2">
                    <AgentsCard agents={agents} />
                    <RisksCard risks={risks} />
                  </div>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2 min-[106.25rem]:grid-cols-4">
                <ActivityCard entries={selectedAudit} />
                <MilestonesCard milestones={projectMilestones(selected, selectedAudit)} />
                <PlannedVsActualCard rows={comparison} />
                <LearningsCard learnings={learnings(comparison)} />
              </div>
            </>
          ) : null}

          {detailTab === "pipeline" ? (
            <Card className="min-w-0">
              <CardHeader>
                <CardTitle>Pipeline del proyecto</CardTitle>
                <CardAction>
                  <DataProvenanceBadge status="verified" compact tooltip="Cada fase enseña lo mismo que su pantalla: score, gate o estado." />
                </CardAction>
              </CardHeader>
              <CardContent>
                <ul className="divide-y text-sm">
                  {selected.phases.map((phase) => (
                    <li key={phase.key} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0">
                      <Link href={phase.href} className="min-w-0 font-medium text-primary underline-offset-4 hover:underline">
                        {phase.label}
                      </Link>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">{phase.detail}</span>
                        <LevelChip tone={phase.state === "done" ? "ok" : phase.state === "blocked" ? "bad" : phase.state === "current" ? "warn" : "neutral"}>
                          {phase.state === "done" ? "Completada" : phase.state === "current" ? "En curso" : phase.state === "blocked" ? "Bloqueada" : "Pendiente"}
                        </LevelChip>
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}

          {detailTab === "hitos" ? <MilestonesCard milestones={projectMilestones(selected, selectedAudit)} /> : null}

          {detailTab === "metricas" ? (
            <div className="space-y-4">
              <KeyMetricsCard metrics={metrics} />
              <PlannedVsActualCard rows={comparison} />
              <LearningsCard learnings={learnings(comparison)} />
            </div>
          ) : null}

          {detailTab === "finanzas" ? (
            <ProjectFinanceCard
              project={selected}
              monthlyRevenue={source ? baseline.inputs.salePrice * baseline.inputs.monthlyOrders : 0}
              unitContribution={source ? economics.contribution : 0}
              capitalLimit={capitalLimit}
            />
          ) : null}

          {detailTab === "documentos" ? <DocumentsCard /> : null}

          {detailTab === "actividad" ? <ActivityCard entries={selectedAudit} limit={20} /> : null}
        </div>
      </div>

      <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <Truck className="size-3.5" />
        {formatInteger(productData.length)} proyectos vienen de productos reales
        {backend.length > 0 ? ` · ${formatInteger(backend.length)} del Director ejecutivo` : " · el Director ejecutivo no tiene proyectos creados"} ·
        el resto son de demostración.
      </p>
    </div>
  );
}
