"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { Menu } from "@base-ui/react/menu";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Bookmark,
  BookmarkCheck,
  Box,
  Brain,
  CalendarDays,
  ChevronRight,
  Ellipsis,
  Filter,
  Globe,
  Lightbulb,
  ListChecks,
  Loader2,
  PackageSearch,
  Radar,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Tag,
  Target,
  Trash2,
  TrendingUp,
  Truck,
} from "lucide-react";
import { ApiError, api, type Product, type ResearchCandidate } from "@/lib/api";
import { DEMO_FILTERS, DEMO_INTEREST_BY_SOURCE } from "@/lib/demo/research";
import {
  CATEGORY_LABEL,
  RADAR_KEYS,
  buildRows,
  radarAverage,
  topInsight,
  type Level,
  type RadarKey,
  type ResearchRow,
  type Risk,
} from "@/lib/research-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { HeaderClock } from "@/components/header-clock";
import { HeaderTile } from "@/components/header-tile";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { LineChart } from "@/components/line-chart";
import { PageHeader } from "@/components/page-header";
import { RadarChart } from "@/components/radar-chart";
import { Sparkline } from "@/components/sparkline";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { RESEARCH_DESCRIPTION, RESEARCH_TITLE } from "./copy";

const MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

const RADAR_LABEL: Record<RadarKey, string> = {
  demand: "Demanda",
  future: "Futuro",
  profitability: "Rentabilidad",
  logistics: "Logística",
  regulation: "Regulación",
  scalability: "Escalabilidad",
};

/** Alta demanda es buena; alta competencia, mala. */
const DEMAND_TONE: Record<Level, LevelTone> = { Alta: "ok", Media: "warn", Baja: "bad" };
const COMPETITION_TONE: Record<Level, LevelTone> = { Baja: "ok", Media: "warn", Alta: "bad" };
const RISK_TONE: Record<Risk, LevelTone> = { Bajo: "ok", Medio: "warn", Alto: "bad" };

function scoreTone(score: number): string {
  return score >= 75 ? "bg-primary text-primary-foreground" : score >= 60 ? "bg-primary/25 text-primary" : "bg-warning/20 text-warning";
}

// --- «Seguir»: preferencia de este navegador (localStorage) ---------------------

const FOLLOW_KEY = "amazona.research.followed";
const followListeners = new Set<() => void>();

function readFollowed(): string {
  try {
    return window.localStorage.getItem(FOLLOW_KEY) ?? "[]";
  } catch {
    return "[]";
  }
}

function useFollowed(): [Set<string>, (id: string) => void] {
  const raw = useSyncExternalStore(
    (onChange) => {
      followListeners.add(onChange);
      return () => followListeners.delete(onChange);
    },
    readFollowed,
    () => "[]",
  );
  const followed = useMemo(() => new Set<string>(JSON.parse(raw) as string[]), [raw]);
  function toggle(id: string) {
    const next = new Set(followed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    try {
      window.localStorage.setItem(FOLLOW_KEY, JSON.stringify([...next]));
    } catch {
      // sin almacenamiento (modo privado): el seguimiento no persiste
    }
    followListeners.forEach((listener) => listener());
  }
  return [followed, toggle];
}

// --- Piezas -----------------------------------------------------------------------

function FilterSelect({
  icon: Icon,
  label,
  value,
  options,
  onChange,
}: {
  icon: typeof Globe;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
      <Icon className="size-4 shrink-0" />
      <span className="shrink-0">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm text-foreground outline-none focus-visible:border-ring"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-popover">
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ProductThumb({ className }: { className?: string }) {
  return (
    <div className={cn("flex shrink-0 items-center justify-center rounded-lg border bg-background/60 text-primary", className)}>
      <Box className="size-1/2" />
    </div>
  );
}

function OpportunityCard({
  row,
  rank,
  growth,
  trend,
  selected,
  following,
  onSelect,
  onAnalyze,
  onFollow,
}: {
  row: ResearchRow;
  rank: number;
  growth: number;
  trend: number[];
  selected: boolean;
  following: boolean;
  onSelect: () => void;
  onAnalyze: () => void;
  onFollow: () => void;
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-xl border bg-background/40 p-4 transition-colors",
        selected && "border-primary/60 shadow-[0_0_18px_-10px_var(--emerald)]",
      )}
    >
      <button type="button" onClick={onSelect} className="flex items-start gap-3 text-left" aria-pressed={selected}>
        <ProductThumb className="size-14" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{row.name}</p>
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            {row.categoryLabel} <ChevronRight className="size-3" /> {row.subcategory}
          </p>
        </div>
        <span className="rounded-md border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-xs font-semibold text-primary">
          #{rank}
        </span>
      </button>

      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">Score de oportunidad</p>
          <p className="text-2xl font-semibold text-primary">
            {row.score}
            <span className="text-sm text-foreground">/100</span>
          </p>
          <div className="mt-1 h-1.5 rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${row.score}%` }} />
          </div>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-2">
            <Sparkline values={trend} />
            <span className="text-sm font-semibold text-primary">+{growth} %</span>
          </div>
          <p className="text-[11px] text-muted-foreground">Crecimiento ({trend.length}m)</p>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,0.95fr)_minmax(0,1fr)] gap-3 text-xs">
        <dl className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1.5 text-muted-foreground">
              <TrendingUp className="size-3.5" /> Demanda
            </dt>
            <dd>
              <LevelChip tone={DEMAND_TONE[row.demand]}>{row.demand}</LevelChip>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1.5 text-muted-foreground">
              <Target className="size-3.5" /> Competencia
            </dt>
            <dd>
              <LevelChip tone={COMPETITION_TONE[row.competition]}>{row.competition}</LevelChip>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-2">
            <dt className="flex items-center gap-1.5 text-muted-foreground">
              <ShieldCheck className="size-3.5" /> Margen
            </dt>
            <dd>
              <LevelChip tone="ok">
                {row.margin[0]}–{row.margin[1]} %
              </LevelChip>
            </dd>
          </div>
        </dl>
        <ul className="space-y-1.5 text-[11px] leading-tight">
          {row.insights.map((insight) => (
            <li key={insight} className="flex items-start gap-1.5 text-muted-foreground">
              <span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary" /> {insight}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto grid grid-cols-2 gap-2">
        <Button onClick={onAnalyze}>
          <Search /> Analizar
        </Button>
        <Button variant="outline" onClick={onFollow} aria-pressed={following}>
          {following ? <BookmarkCheck /> : <Bookmark />}
          {following ? "Siguiendo" : "Seguir"}
        </Button>
      </div>
    </div>
  );
}

// --- Pantalla -----------------------------------------------------------------------

export function ResearchWorkspace({
  products,
  candidates,
  runIds,
}: {
  products: Product[];
  candidates: ResearchCandidate[];
  runIds: string[];
}) {
  const router = useRouter();
  const [followed, toggleFollow] = useFollowed();

  const [query, setQuery] = useState("");
  const [market, setMarket] = useState(DEMO_FILTERS.markets[0]);
  const [category, setCategory] = useState("all");
  const [months, setMonths] = useState(12);
  const [businessModel, setBusinessModel] = useState(DEMO_FILTERS.businessModels[0]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [maxResults, setMaxResults] = useState(5);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rows = useMemo(() => buildRows(products, candidates), [products, candidates]);
  const filtered = rows.filter(
    (r) =>
      (category === "all" || r.category === category) &&
      r.score >= minScore &&
      (!query.trim() || `${r.name} ${r.categoryLabel} ${r.subcategory}`.toLowerCase().includes(query.trim().toLowerCase())),
  );
  const selected = rows.find((r) => r.productId === selectedId) ?? filtered[0] ?? rows[0];
  const average = radarAverage(rows);
  const insight = topInsight(rows);
  const hasDemoSignals = rows.some((r) => r.isDemo);

  // Tendencia e interés según el periodo elegido.
  const windowed = (series: number[]) => series.slice(-months);
  const growthOf = (series: number[]) => {
    const w = windowed(series);
    return Math.round((w[w.length - 1] / w[0] - 1) * 100);
  };
  const monthLabels = MONTHS.slice(-months);

  async function analyzeMarket() {
    setError(null);
    setRunning(true);
    try {
      const categories = category === "all" ? Object.keys(CATEGORY_LABEL) : [category];
      const keywords = query
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);
      const runs = await Promise.all(
        categories.map((c) => api.createResearchRun({ category: c, keywords, max_results: maxResults })),
      );
      const ids = [...runs.map((r) => r.correlation_id), ...runIds].slice(0, 5);
      router.replace(`/research?${new URLSearchParams({ runs: ids.join(",") }).toString()}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La investigación falló.");
    } finally {
      setRunning(false);
    }
  }

  function analyze(row: ResearchRow) {
    router.push(`/economics?${new URLSearchParams({ product_id: row.productId }).toString()}`);
  }

  function findSuppliers(row: ResearchRow) {
    router.push(`/sourcing?${new URLSearchParams({ product_id: row.productId, category: row.category }).toString()}`);
  }

  function validate(row: ResearchRow) {
    const params = new URLSearchParams({
      title: `Validar oportunidad: ${row.name}`,
      product_name: row.name,
      category: row.category,
      demand_signal: row.radar.demand.toFixed(2),
      competition_level: row.competition,
    });
    router.push(`/ceo?${params.toString()}`);
  }

  const columns: DataTableColumn<ResearchRow>[] = [
    {
      key: "product",
      header: "Producto",
      cell: (r) => (
        <span className="flex items-center gap-2.5">
          <ProductThumb className="size-8" />
          <span className="font-medium">{r.name}</span>
        </span>
      ),
      sortValue: (r) => r.name,
      exportValue: (r) => r.name,
    },
    { key: "category", header: "Categoría", cell: (r) => r.categoryLabel, sortValue: (r) => r.categoryLabel, exportValue: (r) => r.categoryLabel },
    {
      key: "demand",
      header: "Demanda",
      cell: (r) => <LevelChip tone={DEMAND_TONE[r.demand]}>{r.demand}</LevelChip>,
      sortValue: (r) => r.radar.demand,
      exportValue: (r) => r.demand,
    },
    {
      key: "trend",
      header: "Tendencia",
      cell: (r) => (
        <span className="flex items-center gap-2">
          <Sparkline values={windowed(r.trend)} width={56} height={20} />
          <span className="text-primary tabular-nums">+{growthOf(r.trend)} %</span>
        </span>
      ),
      sortValue: (r) => growthOf(r.trend),
      exportValue: (r) => `${growthOf(r.trend)} %`,
    },
    {
      key: "competition",
      header: "Competencia",
      cell: (r) => <LevelChip tone={COMPETITION_TONE[r.competition]}>{r.competition}</LevelChip>,
      exportValue: (r) => r.competition,
    },
    {
      key: "margin",
      header: "Margen",
      cell: (r) => (
        <span className="text-primary tabular-nums">
          {r.margin[0]}–{r.margin[1]} %
        </span>
      ),
      sortValue: (r) => r.margin[0],
      exportValue: (r) => `${r.margin[0]}-${r.margin[1]} %`,
    },
    {
      key: "risk",
      header: "Riesgo",
      cell: (r) => <LevelChip tone={RISK_TONE[r.risk]}>{r.risk}</LevelChip>,
      exportValue: (r) => r.risk,
    },
    {
      key: "score",
      header: "Score",
      cell: (r) => (
        <span className={cn("inline-flex min-w-10 justify-center rounded-md px-2 py-0.5 text-sm font-semibold", scoreTone(r.score))}>
          {r.score}
        </span>
      ),
      sortValue: (r) => r.score,
      exportValue: (r) => r.score,
    },
    {
      key: "actions",
      header: "",
      cell: (r) => (
        <Menu.Root>
          <Menu.Trigger render={<Button variant="ghost" size="icon-sm" aria-label={`Acciones de ${r.name}`} />}>
            <Ellipsis />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Positioner sideOffset={4} align="end" className="z-50">
              <Menu.Popup className="min-w-52 rounded-lg border bg-popover p-1 text-sm shadow-lg outline-none">
                {[
                  { label: "Analizar economía", icon: BarChart3, run: () => analyze(r) },
                  { label: "Buscar proveedores", icon: Truck, run: () => findSuppliers(r) },
                  { label: "Validar con el Director ejecutivo", icon: Brain, run: () => validate(r) },
                  { label: followed.has(r.productId) ? "Dejar de seguir" : "Seguir", icon: Bookmark, run: () => toggleFollow(r.productId) },
                ].map((item) => (
                  <Menu.Item
                    key={item.label}
                    onClick={item.run}
                    className="flex cursor-default items-center gap-2 rounded-md px-2.5 py-2 outline-none data-highlighted:bg-panel-hover"
                  >
                    <item.icon className="size-4" /> {item.label}
                  </Menu.Item>
                ))}
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      ),
    },
  ];

  const radarAxes = RADAR_KEYS.map((key) => ({ key, label: RADAR_LABEL[key] }));

  return (
    <div className="space-y-5">
      <PageHeader
        title={RESEARCH_TITLE}
        description={RESEARCH_DESCRIPTION}
        actions={
          <>
            {hasDemoSignals ? (
              <DataProvenanceBadge
                status="demo"
                tooltip="Incluye datos de demostración: señales de los productos no investigados en esta sesión, tendencia, margen preliminar, subcategoría, ideas clave, interés por fuente y los filtros de mercado y modelo de negocio (aún no se envían al agente)."
              />
            ) : null}
            <HeaderClock />
            <HeaderTile label="Modo" value="Simulación (señales de fixtures)" />
          </>
        }
      />

      {/* Búsqueda y filtros */}
      <Card>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row">
            <label className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void analyzeMarket();
                }}
                placeholder="Buscar productos, problemas, categorías o tendencias…"
                aria-label="Buscar productos"
                className="h-12 w-full rounded-lg border bg-background/60 pr-4 pl-12 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/40"
              />
            </label>
            <Button size="lg" className="h-12 px-8 text-base" onClick={() => void analyzeMarket()} disabled={running}>
              {running ? <Loader2 className="animate-spin" /> : <BarChart3 />}
              {running ? "Analizando…" : "Analizar mercado"}
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <FilterSelect
              icon={Globe}
              label="Mercado"
              value={market}
              options={DEMO_FILTERS.markets.map((m) => ({ value: m, label: m }))}
              onChange={setMarket}
            />
            <FilterSelect
              icon={Tag}
              label="Categoría"
              value={category}
              options={[{ value: "all", label: "Todas" }, ...Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))]}
              onChange={setCategory}
            />
            <FilterSelect
              icon={CalendarDays}
              label="Periodo"
              value={String(months)}
              options={DEMO_FILTERS.periods.map((p) => ({ value: String(p.months), label: p.label }))}
              onChange={(v) => setMonths(Number(v))}
            />
            <FilterSelect
              icon={Box}
              label="Modelo de negocio"
              value={businessModel}
              options={DEMO_FILTERS.businessModels.map((m) => ({ value: m, label: m }))}
              onChange={setBusinessModel}
            />
            <Button variant="outline" onClick={() => setShowAdvanced((v) => !v)} aria-expanded={showAdvanced}>
              <SlidersHorizontal /> Filtros avanzados
            </Button>
          </div>
          {showAdvanced ? (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border bg-background/40 p-3 text-sm">
              <label className="flex items-center gap-3 text-muted-foreground">
                Score mínimo
                <input
                  type="range"
                  min={0}
                  max={90}
                  step={5}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  className="w-40 accent-primary"
                />
                <span className="w-8 text-foreground tabular-nums">{minScore}</span>
              </label>
              <label className="flex items-center gap-3 text-muted-foreground">
                Resultados por categoría al analizar
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={maxResults}
                  onChange={(e) => setMaxResults(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
                  className="w-16 rounded-md border bg-background/60 px-2 py-1 text-foreground"
                />
              </label>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>La investigación falló</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {rows.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Sin productos investigados todavía"
              description="Pulsa «Analizar mercado» para que el agente de investigación proponga candidatos."
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2.6fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Radar className="size-5 text-primary" /> Radar de oportunidades
                </CardTitle>
                <CardDescription>Productos con mayor potencial según las señales de mercado.</CardDescription>
                <CardAction>
                  <Button size="xs" variant="ghost" className="text-primary" nativeButton={false} render={<a href="#resultados" />}>
                    <span className="hidden sm:inline">Ver todas las oportunidades</span>
                    <span className="sm:hidden">Ver todas</span> <ArrowRight />
                  </Button>
                </CardAction>
              </CardHeader>
              <CardContent>
                {filtered.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">Ningún producto cumple los filtros.</p>
                ) : (
                  <div className="grid gap-3 lg:grid-cols-3">
                    {filtered.slice(0, 3).map((row, k) => (
                      <OpportunityCard
                        key={row.productId}
                        row={row}
                        rank={k + 1}
                        growth={growthOf(row.trend)}
                        trend={windowed(row.trend)}
                        selected={selected?.productId === row.productId}
                        following={followed.has(row.productId)}
                        onSelect={() => setSelectedId(row.productId)}
                        onAnalyze={() => analyze(row)}
                        onFollow={() => toggleFollow(row.productId)}
                      />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card id="resultados" className="scroll-mt-4">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <ListChecks className="size-5 text-primary" /> Resultados
                </CardTitle>
                <CardDescription>Productos candidatos ordenados por potencial de oportunidad.</CardDescription>
                <CardAction className="text-xs text-muted-foreground">
                  Mostrando {filtered.length} de {rows.length} resultados
                </CardAction>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <DataTable
                  columns={columns}
                  rows={filtered}
                  getRowId={(r) => r.productId}
                  selectedId={selected?.productId}
                  onSelect={(r) => setSelectedId(r.productId)}
                  exportFileName="investigacion-resultados"
                  emptyMessage="Ningún producto cumple los filtros."
                />
              </CardContent>
            </Card>
          </div>

          <div className="min-w-0 space-y-4">
            {selected ? (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <BarChart3 className="size-5 text-primary" /> Radar de oportunidad AMAZONA
                  </CardTitle>
                  <CardDescription>
                    {selected.name}: análisis multidimensional frente a la media de los candidatos.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <RadarChart
                    axes={radarAxes}
                    series={[
                      { label: "Producto analizado", color: "var(--emerald-bright)", values: selected.radar },
                      { label: "Media del mercado", color: "var(--text-secondary)", values: average },
                    ]}
                  />
                  <p className="mt-2 text-[11px] text-muted-foreground">{selected.rationale}</p>
                </CardContent>
              </Card>
            ) : null}

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BarChart3 className="size-5 text-primary" /> Resumen de investigación
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                {[
                  { icon: Radar, value: rows.length, label: "Oportunidades encontradas", tone: "text-primary" },
                  { icon: Filter, value: filtered.length, label: "Tras filtros aplicados", tone: "text-primary" },
                  { icon: Bookmark, value: rows.filter((r) => followed.has(r.productId)).length, label: "En seguimiento", tone: "text-primary" },
                  { icon: Trash2, value: rows.filter((r) => r.score < 50).length, label: "Descartadas (score < 50)", tone: "text-destructive" },
                ].map((stat) => (
                  <div key={stat.label} className="min-w-0">
                    <p className="flex items-center gap-2 text-2xl font-semibold">
                      <stat.icon className={cn("size-5", stat.tone)} /> {stat.value}
                    </p>
                    <p className="text-xs text-muted-foreground">{stat.label}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingUp className="size-5 text-primary" /> Tendencia de interés por fuente
                </CardTitle>
                <CardDescription>Interés relativo en los últimos {months} meses.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <LineChart
                  ariaLabel="Interés relativo por fuente"
                  series={DEMO_INTEREST_BY_SOURCE.map((s) => ({
                    key: s.key,
                    label: s.label,
                    color: s.color,
                    points: windowed(s.series).map((y, x) => ({ x, y })),
                  }))}
                  formatY={(v) => String(Math.round(v))}
                  formatX={(x) => monthLabels[x] ?? ""}
                  hoverTitle={(x) => monthLabels[x] ?? ""}
                  height={200}
                />
                {insight ? (
                  <div className="flex items-start gap-3 rounded-lg border bg-background/40 p-3 text-xs">
                    <Lightbulb className="size-5 shrink-0 text-warning" />
                    <div>
                      <p className="font-semibold">Insight AMAZONA</p>
                      <p className="text-muted-foreground">{insight}</p>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
