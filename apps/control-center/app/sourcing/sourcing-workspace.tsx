"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Box,
  Brain,
  Calculator,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock,
  GitCompareArrows,
  Loader2,
  PackageCheck,
  PackageSearch,
  Save,
  Scale,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Truck,
  UserCheck,
} from "lucide-react";
import { ApiError, api, type Product, type SupplierQuote } from "@/lib/api";
import { DEMO_PRODUCT_META } from "@/lib/demo/economics";
import { DEMO_SEARCH_OPTIONS, demoQuotes } from "@/lib/demo/sourcing";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { formatEuro, formatInteger } from "@/lib/format";
import { REGION_ANCHORS, REGION_LABELS, regionLabel } from "@/lib/regions";
import { buildRows, categoryLabel } from "@/lib/research-view";
import {
  SUPPLIER_AXES,
  averageAxes,
  compatibility,
  filterSuppliers,
  landedBreakdown,
  rankSuppliers,
  topBadges,
  type RankedSupplier,
  type SearchParams,
  type SupplierRisk,
} from "@/lib/sourcing-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { Flag } from "@/components/flag";
import { HeaderClock } from "@/components/header-clock";
import { HeaderTile } from "@/components/header-tile";
import { LevelChip, type LevelTone } from "@/components/level-chip";
import { NextStepBar } from "@/components/next-step-bar";
import { PageHeader } from "@/components/page-header";
import { RadarChart } from "@/components/radar-chart";
import { RouteMap, type MapPoint, type MapRoute } from "@/components/route-map";
import { ScoreGauge } from "@/components/score-gauge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { SOURCING_DESCRIPTION, SOURCING_TITLE } from "./copy";

const DESTINATIONS = ["eu", "mexico", "china", "vietnam"] as const;
const DESTINATION_SHORT: Record<string, string> = { eu: "UE", mexico: "México", china: "China", vietnam: "Vietnam" };
const DESTINATION_FLAG: Record<string, "eu" | "mx" | "cn" | "vn"> = { eu: "eu", mexico: "mx", china: "cn", vietnam: "vn" };
const RISK_TONE: Record<SupplierRisk, LevelTone> = { Bajo: "ok", Medio: "warn", Alto: "bad" };
const SELECT_CLASS =
  "w-full min-w-0 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring";
const PRODUCT_STATUS_LABEL: Record<string, string> = { CANDIDATE: "Candidato" };

function quoteName(quote: SupplierQuote): string {
  return quote.data?.name ?? quote.supplier_id;
}

function days([min, max]: [number, number]): string {
  return `${min}–${max} días`;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="min-w-0 space-y-1 text-xs text-muted-foreground">
      <span className="block">{label}</span>
      {children}
    </label>
  );
}

function SupplierCard({
  supplier,
  destination,
  badge,
  selected,
  comparing,
  onSelect,
  onProfile,
  onAnalyze,
  onCompare,
}: {
  supplier: RankedSupplier;
  destination: string;
  badge?: string;
  selected: boolean;
  comparing: boolean;
  onSelect: () => void;
  onProfile: () => void;
  onAnalyze: () => void;
  onCompare: () => void;
}) {
  const { quote, profile } = supplier;
  const certs = profile.certifications.join(", ");
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-xl border bg-background/40 p-3.5 transition-colors",
        selected && "border-primary/60 shadow-[0_0_18px_-10px_var(--emerald)]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onSelect} className="min-w-0 flex-1 text-left" aria-pressed={selected}>
          <p className="line-clamp-2 text-[13px] leading-snug font-semibold">{quoteName(quote)}</p>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Flag code={profile.flag} /> {profile.country} · {profile.city}
          </p>
        </button>
        <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={onProfile}>
          Ver perfil
        </button>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex size-16 shrink-0 items-center justify-center rounded-lg border bg-background/60 text-primary">
          <Box className="size-7" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-muted-foreground">Score proveedor</p>
          <ScoreGauge value={supplier.score} className="w-24" />
        </div>
      </div>
      <div>
        <p className="text-[11px] text-muted-foreground">Precio por unidad</p>
        <p className="text-lg font-semibold text-primary">{formatEuro(quote.unit_price)}</p>
      </div>

      <dl className="space-y-1.5 text-xs">
        {[
          ["MOQ", `${formatInteger(quote.moq)} ${quote.moq === 1 ? "unidad" : "unidades"}`],
          [`Entrega a ${DESTINATION_SHORT[destination] ?? destination}`, days(profile.delivery)],
          ["Envío directo", profile.directShipping ? "Sí" : "No"],
          ["Certificaciones", profile.certificationPending ? `${certs} (pendiente)` : certs],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="truncate text-right font-medium">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-auto grid grid-cols-2 gap-2">
        <Button size="sm" onClick={onAnalyze}>
          Analizar
        </Button>
        <Button
          size="sm"
          variant={comparing ? "secondary" : "outline"}
          onClick={onCompare}
          aria-pressed={comparing}
          disabled={selected}
          title={selected ? "Es el proveedor seleccionado: elige otro para compararlo" : undefined}
        >
          {comparing ? "Comparando" : "Comparar"}
        </Button>
      </div>
      {badge ? (
        <Badge variant="outline" className="mx-auto gap-1 border-primary/40 text-primary">
          <Star className="size-3" /> {badge}
        </Badge>
      ) : null}
    </div>
  );
}

export function SourcingWorkspace({
  products,
  productId,
  quotes,
  initialSearch,
}: {
  products: Product[];
  productId?: string;
  quotes: SupplierQuote[];
  initialSearch: SearchParams;
}) {
  const router = useRouter();
  const product = products.find((p) => p.id === productId);

  const [search, setSearch] = useState<SearchParams>(initialSearch);
  const [showMore, setShowMore] = useState(initialSearch.verifiedOnly);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [changingProduct, setChangingProduct] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchedAt, setSearchedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isDemo = quotes.length === 0;
  const allQuotes = useMemo(
    () => (isDemo ? demoQuotes(productId ?? "demo") : dedupeQuotesBySupplier(quotes)),
    [isDemo, quotes, productId],
  );
  const ranked = useMemo(() => rankSuppliers(allQuotes), [allQuotes]);
  const shown = filterSuppliers(ranked, search);
  const badges = topBadges(shown, search.destination);
  const selected = shown.find((s) => s.quote.id === selectedId) ?? shown[0];
  const compared = shown.find((s) => s.quote.id === compareId && s.quote.id !== selected?.quote.id);

  if (products.length === 0 || !product) {
    return (
      <div>
        <PageHeader title={SOURCING_TITLE} description={SOURCING_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay productos para abastecer"
              description="Los proveedores se buscan para un producto ya investigado. Lanza primero una investigación."
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

  const researchScore = buildRows([product], [])[0].score;

  function update<K extends keyof SearchParams>(key: K, value: SearchParams[K]) {
    setSearch((current) => ({ ...current, [key]: value }));
    setSavedAt(null);
  }

  function saveSearch() {
    const params = new URLSearchParams({ product_id: product!.id, dest: search.destination, logistics: search.logistics });
    if (search.origin) params.set("origin", search.origin);
    if (search.minPrice) params.set("pmin", search.minPrice);
    if (search.maxPrice) params.set("pmax", search.maxPrice);
    if (search.maxLeadTime) params.set("lead", search.maxLeadTime);
    if (search.maxMoq) params.set("moq", search.maxMoq);
    if (search.requireCertification) params.set("cert", "1");
    if (search.verifiedOnly) params.set("verified", "1");
    if (search.maxResults !== 5) params.set("max", String(search.maxResults));
    router.replace(`/sourcing?${params.toString()}`, { scroll: false });
    setSavedAt(new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }));
  }

  async function runSearch() {
    setError(null);
    setSearching(true);
    try {
      await api.createSourcingRun({
        product_id: product!.id,
        category: product!.category,
        destination_region: search.destination,
        max_results: search.maxResults,
      });
      setSearchedAt(new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }));
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La búsqueda de proveedores falló.");
    } finally {
      setSearching(false);
    }
  }

  function analyzeEconomics(quote: SupplierQuote) {
    const params = new URLSearchParams({ product_id: product!.id });
    if (!isDemo) params.set("supplier_quote_id", quote.id);
    router.push(`/economics?${params.toString()}`);
  }

  function validateWithCeo(quote: SupplierQuote) {
    const params = new URLSearchParams({
      title: `Validar abastecimiento con ${quoteName(quote)} para ${product!.name}`,
      unit_cost: String(quote.unit_price),
      lead_time_days: String(quote.lead_time_days),
      supplier_verified: String(quote.verified),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function toggleCompare(quote: SupplierQuote) {
    setCompareId((current) => (current === quote.id ? null : quote.id));
  }

  function showProfile(quote: SupplierQuote) {
    setSelectedId(quote.id);
    document.getElementById("score-proveedor")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // Mapa: una región de origen por proveedor visible + el destino.
  const origins = [...new Set(shown.map((s) => s.quote.data?.region).filter((r): r is string => Boolean(r && REGION_ANCHORS[r])))];
  const mapPoints: MapPoint[] = [...new Set([...origins, search.destination])]
    .filter((region) => REGION_ANCHORS[region])
    .map((region) => ({
      id: region,
      label: region === search.destination ? `${regionLabel(region)} (destino)` : regionLabel(region),
      lonLat: REGION_ANCHORS[region],
      kind: region === search.destination ? (origins.includes(region) ? "both" : "destination") : "origin",
    }));
  const mapRoutes: MapRoute[] = origins
    .filter((o) => o !== search.destination && REGION_ANCHORS[search.destination])
    .map((o) => ({ id: `${o}->${search.destination}`, from: o, to: search.destination }));

  const columns: DataTableColumn<RankedSupplier>[] = [
    {
      key: "name",
      header: "Proveedor",
      cell: (s) => <span className="font-medium">{quoteName(s.quote)}</span>,
      sortValue: (s) => quoteName(s.quote),
      exportValue: (s) => quoteName(s.quote),
    },
    {
      key: "country",
      header: "País",
      cell: (s) => (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <Flag code={s.profile.flag} /> {s.profile.country}
        </span>
      ),
      sortValue: (s) => s.profile.country,
      exportValue: (s) => s.profile.country,
    },
    {
      key: "price",
      header: "Precio (€)",
      align: "right",
      cell: (s) => formatEuro(s.quote.unit_price),
      sortValue: (s) => s.quote.unit_price,
      exportValue: (s) => s.quote.unit_price,
    },
    { key: "moq", header: "MOQ", align: "right", cell: (s) => formatInteger(s.quote.moq), sortValue: (s) => s.quote.moq, exportValue: (s) => s.quote.moq },
    {
      key: "delivery",
      header: "Entrega",
      cell: (s) => <span className="whitespace-nowrap">{days(s.profile.delivery)}</span>,
      sortValue: (s) => s.profile.delivery[0],
      exportValue: (s) => days(s.profile.delivery),
    },
    {
      key: "direct",
      header: "Envío directo",
      cell: (s) => (s.profile.directShipping ? "Sí" : "No"),
      exportValue: (s) => (s.profile.directShipping ? "Sí" : "No"),
    },
    {
      key: "certs",
      header: "Certificaciones",
      cell: (s) => (
        <span className="whitespace-nowrap">
          {s.profile.certificationPending ? `${s.profile.certifications[0]} (pendiente)` : s.profile.certifications.join(", ")}
        </span>
      ),
      exportValue: (s) => s.profile.certifications.join(" "),
    },
    {
      key: "risk",
      header: "Riesgo",
      cell: (s) => <LevelChip tone={RISK_TONE[s.risk]}>{s.risk}</LevelChip>,
      exportValue: (s) => s.risk,
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      cell: (s) => <span className="font-semibold text-primary">{s.score}</span>,
      sortValue: (s) => s.score,
      exportValue: (s) => s.score,
    },
    {
      key: "actions",
      header: "Acciones",
      cell: (s) => (
        <div className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
          <Button size="icon-sm" variant="ghost" title="Analizar economía" aria-label={`Analizar economía de ${quoteName(s.quote)}`} onClick={() => analyzeEconomics(s.quote)}>
            <Calculator />
          </Button>
          <Button size="icon-sm" variant="ghost" title="Comparar" aria-label={`Comparar ${quoteName(s.quote)}`} onClick={() => toggleCompare(s.quote)}>
            <GitCompareArrows />
          </Button>
          <Button size="icon-sm" variant="ghost" title="Validar con el Director ejecutivo" aria-label={`Validar ${quoteName(s.quote)} con el Director ejecutivo`} onClick={() => validateWithCeo(s.quote)}>
            <Brain />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title={SOURCING_TITLE}
        description={SOURCING_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge
              status="demo"
              tooltip={`Incluye datos de demostración: ${isDemo ? "los proveedores y sus cotizaciones (este producto aún no tiene ninguna real); " : ""}país y ciudad, certificaciones, envío directo, plazos de entrega, calidad, compliance, escalabilidad, compatibilidad, desglose del coste, score de investigación y descripción del producto.`}
            />
            <HeaderClock />
            <HeaderTile label="Modo" value="Búsqueda de proveedores" />
          </>
        }
      />

      {/* Producto · Parámetros · Resumen */}
      <section className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1.35fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Producto seleccionado</CardTitle>
            <CardAction>
              <Button size="xs" variant="ghost" className="text-primary" onClick={() => setChangingProduct((v) => !v)}>
                Cambiar
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            {changingProduct ? (
              <select
                aria-label="Producto"
                value={product.id}
                onChange={(e) => router.push(`/sourcing?${new URLSearchParams({ product_id: e.target.value }).toString()}`)}
                className={SELECT_CLASS}
              >
                {products.map((p) => (
                  <option key={p.id} value={p.id} className="bg-popover">
                    {p.name}
                  </option>
                ))}
              </select>
            ) : null}
            <div className="flex gap-3">
              <div className="flex size-20 shrink-0 items-center justify-center rounded-xl border bg-background/60 text-primary">
                <Box className="size-9" />
              </div>
              <div className="min-w-0 space-y-1.5">
                <p className="truncate font-semibold">{product.name}</p>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline" className="border-primary/40 text-primary">
                    {categoryLabel(product.category)}
                  </Badge>
                  <Badge variant="outline">{PRODUCT_STATUS_LABEL[product.status] ?? product.status}</Badge>
                </div>
                <p className="line-clamp-2 text-xs text-muted-foreground">{DEMO_PRODUCT_META.description}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 text-sm">
              <span className="rounded-lg border bg-background/40 px-3 py-1.5">
                <span className="text-muted-foreground">Investigación: </span>
                <span className="font-semibold text-primary">{researchScore}/100</span>
              </span>
              <span className="rounded-lg border bg-background/40 px-3 py-1.5">
                <span className="text-muted-foreground">Mercado objetivo: </span>
                <span className="font-semibold text-primary">{DEMO_PRODUCT_META.marketLabel}</span>
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Parámetros de búsqueda</CardTitle>
            <CardAction>
              <Button size="xs" variant="ghost" className="text-primary" onClick={saveSearch}>
                {savedAt ? <CheckCircle2 /> : <Save />}
                {savedAt ? `Guardada ${savedAt}` : "Guardar búsqueda"}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Región de destino">
                <select value={search.destination} onChange={(e) => update("destination", e.target.value)} className={SELECT_CLASS}>
                  {DESTINATIONS.map((r) => (
                    <option key={r} value={r} className="bg-popover">
                      {r === "eu" ? "España + UE" : REGION_LABELS[r]}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Origen proveedor">
                <select value={search.origin} onChange={(e) => update("origin", e.target.value)} className={SELECT_CLASS}>
                  <option value="" className="bg-popover">
                    Global
                  </option>
                  {Object.entries(REGION_LABELS).map(([value, label]) => (
                    <option key={value} value={value} className="bg-popover">
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Modelo logístico">
                <select value={search.logistics} onChange={(e) => update("logistics", e.target.value)} className={SELECT_CLASS}>
                  {DEMO_SEARCH_OPTIONS.logisticsModels.map((o) => (
                    <option key={o.value} value={o.value} className="bg-popover">
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Precio objetivo (€)">
                <span className="grid grid-cols-2 gap-2">
                  <input inputMode="decimal" placeholder="Mín." value={search.minPrice} onChange={(e) => update("minPrice", e.target.value)} className={SELECT_CLASS} aria-label="Precio mínimo" />
                  <input inputMode="decimal" placeholder="Máx." value={search.maxPrice} onChange={(e) => update("maxPrice", e.target.value)} className={SELECT_CLASS} aria-label="Precio máximo" />
                </span>
              </Field>
              <Field label="Plazo máximo de entrega">
                <select value={search.maxLeadTime} onChange={(e) => update("maxLeadTime", e.target.value)} className={SELECT_CLASS}>
                  {DEMO_SEARCH_OPTIONS.leadTimes.map((o) => (
                    <option key={o.value} value={o.value} className="bg-popover">
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="MOQ máximo">
                <select value={search.maxMoq} onChange={(e) => update("maxMoq", e.target.value)} className={SELECT_CLASS}>
                  {DEMO_SEARCH_OPTIONS.moqs.map((o) => (
                    <option key={o.value} value={o.value} className="bg-popover">
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <span className="text-xs text-muted-foreground">Filtros avanzados</span>
              <Button
                size="xs"
                variant={search.requireCertification ? "secondary" : "outline"}
                aria-pressed={search.requireCertification}
                onClick={() => update("requireCertification", !search.requireCertification)}
              >
                <ShieldCheck /> Certificaciones
              </Button>
              <Button size="xs" variant="outline" disabled title="Pendiente: el backend no guarda Incoterms">
                <Truck /> Incoterms
              </Button>
              <Button size="xs" variant="outline" disabled title="Pendiente: el backend no guarda métodos de pago">
                <CircleDollarSign /> Métodos de pago
              </Button>
              <Button size="xs" variant={showMore ? "secondary" : "outline"} aria-expanded={showMore} onClick={() => setShowMore((v) => !v)}>
                <SlidersHorizontal /> Más filtros (2)
              </Button>
            </div>
            {showMore ? (
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={search.verifiedOnly} onChange={(e) => update("verifiedOnly", e.target.checked)} className="accent-primary" />
                  Solo proveedores verificados
                </label>
                <label className="flex items-center gap-2">
                  Resultados por búsqueda
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={search.maxResults}
                    onChange={(e) => update("maxResults", Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
                    className="w-16 rounded-md border bg-background/60 px-2 py-1 text-foreground"
                  />
                </label>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-2 2xl:col-span-1">
          <CardHeader>
            <CardTitle>Resumen de la búsqueda</CardTitle>
            <CardAction>
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Clock className="size-3.5 text-primary" />
                {searchedAt ? `Completada a las ${searchedAt}` : isDemo ? "Proveedores de ejemplo" : "Cotizaciones guardadas"}
              </span>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 2xl:grid-cols-2">
              {[
                { value: allQuotes.length, label: "Proveedores analizados", tone: "text-primary" },
                { value: shown.length, label: "Preseleccionados", tone: "text-primary" },
                { value: Math.min(3, shown.length), label: "Recomendados", tone: "text-primary" },
                { value: allQuotes.length - shown.length, label: "Descartados", tone: "text-destructive" },
              ].map((stat) => (
                <div key={stat.label} className="min-w-0 rounded-lg border bg-background/40 px-2 py-2">
                  <p className={cn("text-xl font-semibold", stat.tone)}>{stat.value}</p>
                  <p className="text-[11px] leading-tight text-muted-foreground">{stat.label}</p>
                </div>
              ))}
            </div>
            <Button size="lg" className="w-full" onClick={() => void runSearch()} disabled={searching}>
              {searching ? <Loader2 className="animate-spin" /> : <Search />}
              {searching ? "Buscando…" : "Buscar proveedores"}
            </Button>
          </CardContent>
        </Card>
      </section>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>La búsqueda de proveedores falló</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {!selected ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Truck}
              title="Ningún proveedor cumple los parámetros"
              description={`Hay ${allQuotes.length} proveedores, pero todos quedan fuera de los filtros que has fijado.`}
            />
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Recomendados · Mapa */}
          <section className="grid gap-4 2xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Proveedores recomendados</CardTitle>
                <CardAction>
                  <Button size="xs" variant="ghost" className="text-primary" nativeButton={false} render={<a href="#listado" />}>
                    Ver todos ({shown.length}) <ChevronRight />
                  </Button>
                </CardAction>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 md:grid-cols-3">
                  {shown.slice(0, 3).map((s) => (
                    <SupplierCard
                      key={s.quote.id}
                      supplier={s}
                      destination={search.destination}
                      badge={badges.get(s.quote.id)}
                      selected={selected.quote.id === s.quote.id}
                      comparing={compared?.quote.id === s.quote.id}
                      onSelect={() => setSelectedId(s.quote.id)}
                      onProfile={() => showProfile(s.quote)}
                      onAnalyze={() => analyzeEconomics(s.quote)}
                      onCompare={() => toggleCompare(s.quote)}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Mapa de proveedores</CardTitle>
              </CardHeader>
              <CardContent className="grid items-start gap-3 md:grid-cols-[minmax(0,1fr)_11.5rem]">
                <RouteMap
                  points={mapPoints}
                  routes={mapRoutes}
                  selectedPointId={selected.quote.data?.region}
                  onSelectPoint={(region) => {
                    const first = shown.find((s) => s.quote.data?.region === region);
                    if (first) setSelectedId(first.quote.id);
                  }}
                />
                <dl className="space-y-3 self-start rounded-lg border bg-background/40 p-3 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Ruta seleccionada</dt>
                    <dd className="flex items-center gap-1.5 font-medium">
                      {selected.profile.city} <ArrowRight className="size-3.5" />
                      {search.destination === "eu" ? "España" : regionLabel(search.destination)}
                      <Flag code={DESTINATION_FLAG[search.destination] ?? "eu"} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Tiempo estimado</dt>
                    <dd className="font-medium">{days(selected.profile.delivery)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Transporte</dt>
                    <dd className="font-medium">{selected.profile.transport}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Coste estimado</dt>
                    <dd className="font-medium">{formatEuro(selected.quote.logistics_cost_per_unit)} / unidad</dd>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="w-full"
                    onClick={() => document.getElementById("coste-total")?.scrollIntoView({ behavior: "smooth", block: "center" })}
                  >
                    Ver detalles de logística
                  </Button>
                </dl>
              </CardContent>
            </Card>
          </section>

          {/* Listado · Coste · Compatibilidad · Score */}
          <section className="grid gap-4 lg:grid-cols-3 min-[1800px]:grid-cols-[minmax(0,1.9fr)_minmax(0,0.95fr)_minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <Card id="listado" className="scroll-mt-4 lg:col-span-3 min-[1800px]:col-span-1">
              <CardHeader>
                <CardTitle>
                  Listado de proveedores <span className="ml-2 text-xs font-normal text-muted-foreground">{shown.length} resultados</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <DataTable
                  columns={columns}
                  rows={shown}
                  getRowId={(s) => s.quote.id}
                  selectedId={selected.quote.id}
                  onSelect={(s) => setSelectedId(s.quote.id)}
                  getSearchText={(s) => `${quoteName(s.quote)} ${s.profile.country} ${s.profile.city}`}
                  searchPlaceholder="Buscar proveedor…"
                  exportFileName={`proveedores-${product.name.toLowerCase().replace(/\s+/g, "-")}`}
                  emptyMessage="Ningún proveedor coincide con la búsqueda."
                />
              </CardContent>
            </Card>

            <Card id="coste-total" className="scroll-mt-4">
              <CardHeader>
                <CardTitle className="text-sm">
                  Coste total estimado <span className="font-normal text-muted-foreground">(Landed Cost)</span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-[13px]">
                <p className="truncate text-xs text-muted-foreground">{quoteName(selected.quote)}</p>
                {landedBreakdown(selected.quote).map((line) =>
                  line.total ? (
                    <div key={line.key} className="mt-2 flex justify-between gap-2 rounded-lg border border-primary/40 bg-primary/10 px-2.5 py-2 font-semibold text-primary">
                      <span>{line.label}</span>
                      <span className="tabular-nums">{formatEuro(line.amount)}</span>
                    </div>
                  ) : (
                    <div key={line.key} className="flex justify-between gap-2 px-0.5 py-0.5">
                      <span className="text-muted-foreground">{line.label}</span>
                      <span className="tabular-nums">{formatEuro(line.amount)}</span>
                    </div>
                  ),
                )}
                <p className="pt-1 text-[10px] text-muted-foreground">
                  Estimación basada en datos promedio. Puede variar según proveedor y condiciones.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Compatibilidad con Amazona</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-[13px]">
                  {compatibility(selected.quote, selected.profile).map((item) => (
                    <li key={item.label} className="flex items-center gap-2">
                      {item.ok ? (
                        <CheckCircle2 className="size-4 shrink-0 text-primary" />
                      ) : (
                        <AlertTriangle className="size-4 shrink-0 text-warning" />
                      )}
                      <span className={cn("min-w-0", !item.ok && "text-muted-foreground")}>{item.label}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            <Card id="score-proveedor" className="scroll-mt-4">
              <CardHeader>
                <CardTitle className="text-sm">Score de proveedor</CardTitle>
              </CardHeader>
              <CardContent>
                <RadarChart
                  axes={[...SUPPLIER_AXES]}
                  centerLabel={`${selected.score}/100`}
                  series={[
                    { label: quoteName(selected.quote), color: "var(--emerald-bright)", values: selected.axes },
                    compared
                      ? { label: quoteName(compared.quote), color: "var(--text-secondary)", values: compared.axes }
                      : { label: "Media de los encontrados", color: "var(--text-secondary)", values: averageAxes(shown) },
                  ]}
                />
              </CardContent>
            </Card>
          </section>
        </>
      )}

      <NextStepBar
        steps={[
          { label: "Proveedor validado", icon: UserCheck, state: selected ? "done" : "current" },
          { label: "Análisis económico", icon: Calculator, state: selected ? "current" : "todo" },
          { label: "Revisión legal", icon: Scale, state: "todo" },
          { label: "Aprobación CEO", icon: Brain, state: "todo" },
          { label: "Integración operativa", icon: PackageCheck, state: "todo" },
        ]}
        action={
          <Button disabled={!selected} onClick={() => selected && analyzeEconomics(selected.quote)}>
            Enviar a análisis económico <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
