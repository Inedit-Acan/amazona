"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  Calculator,
  Check,
  CircleDashed,
  Loader2,
  MapPin,
  PackageCheck,
  PackageSearch,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  Star,
  Truck,
  X,
} from "lucide-react";
import { ApiError, api, type Product, type SupplierQuote } from "@/lib/api";
import {
  DISTINCTION_LABEL,
  SUPPLIER_RADAR_AXES,
  applyFilters,
  averageRadarValues,
  distinctionsFor,
  sortByLandedCost,
  supplierRadarValues,
  type QuoteFilters,
} from "@/lib/sourcing";
import { formatAmount, formatInteger } from "@/lib/format";
import { REGION_ANCHORS, REGION_LABELS, regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { NextStepBar } from "@/components/next-step-bar";
import { RadarChart, type RadarSeries } from "@/components/radar-chart";
import { RouteMap, type MapPoint, type MapRoute } from "@/components/route-map";
import { ScoreGauge } from "@/components/score-gauge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const DESTINATION_REGIONS = ["eu", "mexico", "china", "vietnam"] as const;
const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";

const PRODUCT_STATUS_LABEL: Record<string, string> = { CANDIDATE: "Candidato" };
const PRODUCT_SOURCE_LABEL: Record<string, string> = { research: "Investigación", manual: "Manual" };

/** Criterios de compatibilidad de la spec (§6.9) que el backend no puede
 * evaluar hoy: ninguno de estos campos existe en SupplierQuote. */
const PENDING_COMPATIBILITY = [
  "Dropshipping / envío directo",
  "Packaging neutro",
  "Tracking automático",
  "Stock sincronizable (API/CSV)",
  "Dirección de devoluciones UE",
  "SLA contractual",
  "Pago después de venta",
];

const ADVANCED_FILTERS = ["Origen", "Modelo logístico", "Certificaciones", "Incoterms", "Métodos de pago"];

interface SearchRun {
  quotes: SupplierQuote[];
  destinationRegion: string;
  ranAt: Date;
}

function parseLimit(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function quoteRegion(quote: SupplierQuote): string | undefined {
  return quote.data?.region;
}

function quoteName(quote: SupplierQuote): string {
  return quote.data?.name ?? quote.supplier_id;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2.5">
      <p className="text-xl font-semibold text-primary">{value}</p>
      <p className="text-[11px] leading-tight text-muted-foreground">{label}</p>
    </div>
  );
}

function VerificationChip({ verified }: { verified: boolean }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1 font-medium",
        verified
          ? "border-emerald-500/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          : "border-red-500/30 bg-red-500/15 text-red-600 dark:text-red-400",
      )}
    >
      {verified ? <ShieldCheck className="size-3" /> : <ShieldAlert className="size-3" />}
      {verified ? "Verificado" : "No verificado"}
    </Badge>
  );
}

function SupplierCard({
  quote,
  rank,
  distinctions,
  selected,
  comparing,
  onSelect,
  onCompare,
  onAnalyze,
}: {
  quote: SupplierQuote;
  rank: number;
  distinctions: string[];
  selected: boolean;
  comparing: boolean;
  onSelect: () => void;
  onCompare: () => void;
  onAnalyze: () => void;
}) {
  return (
    <Card
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "cursor-pointer outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring",
        selected && "ring-2 ring-primary shadow-[0_0_18px_-6px_var(--emerald)]",
      )}
    >
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{quoteName(quote)}</p>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
              <MapPin className="size-3" />
              {regionLabel(quoteRegion(quote))}
            </p>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">#{rank}</span>
        </div>

        <ScoreGauge value={quote.reliability_score * 100} label="Fiabilidad" className="mx-auto w-28" />

        <div className="grid grid-cols-2 gap-2 border-t pt-3 text-center">
          <div>
            <p className="text-[11px] text-muted-foreground">Precio</p>
            <p className="text-lg leading-tight font-semibold">{formatAmount(quote.unit_price)}</p>
          </div>
          <div>
            <p className="text-[11px] text-muted-foreground">Entregado</p>
            <p className="text-lg leading-tight font-semibold text-primary">
              {formatAmount(quote.total_landed_cost_per_unit)}
            </p>
          </div>
        </div>

        <dl className="space-y-1.5 text-xs">
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">MOQ</dt>
            <dd className="font-medium">{formatInteger(quote.moq)} uds</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">Entrega</dt>
            <dd className="font-medium">{quote.lead_time_days} días</dd>
          </div>
        </dl>
        <VerificationChip verified={quote.verified} />

        <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
          <Button type="button" size="sm" className="flex-1" onClick={onAnalyze}>
            Analizar
          </Button>
          <Button
            type="button"
            size="sm"
            variant={comparing ? "secondary" : "outline"}
            className="flex-1"
            aria-pressed={comparing}
            onClick={onCompare}
          >
            {comparing ? "Comparando" : "Comparar"}
          </Button>
        </div>

        {distinctions.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {distinctions.map((label) => (
              <Badge key={label} variant="outline" className="gap-1 border-primary/40 text-primary">
                <Star className="size-3" />
                {label}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CompatibilityRow({ state, label, detail }: { state: "pass" | "fail" | "info" | "pending"; label: string; detail?: string }) {
  return (
    <li className={cn("flex items-center gap-2 text-xs", state === "pending" && "text-muted-foreground")}>
      {state === "pass" ? (
        <Check className="size-4 shrink-0 text-emerald-500" />
      ) : state === "fail" ? (
        <X className="size-4 shrink-0 text-red-500" />
      ) : state === "info" ? (
        <PackageCheck className="size-4 shrink-0 text-primary" />
      ) : (
        <CircleDashed className="size-4 shrink-0 opacity-60" />
      )}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {detail ? <span className="shrink-0 font-medium text-foreground">{detail}</span> : null}
      {state === "pending" ? <span className="shrink-0 text-[10px] uppercase tracking-wide">Pendiente</span> : null}
    </li>
  );
}

export function SourcingWorkspace({
  products,
  initialProductId,
}: {
  products: Product[];
  initialProductId?: string;
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(
    products.some((p) => p.id === initialProductId) ? (initialProductId as string) : (products[0]?.id ?? ""),
  );
  const [changingProduct, setChangingProduct] = useState(false);
  const [destinationRegion, setDestinationRegion] = useState<string>("eu");
  const [maxResults, setMaxResults] = useState(5);
  const [maxUnitPrice, setMaxUnitPrice] = useState("");
  const [maxLeadTime, setMaxLeadTime] = useState("");
  const [maxMoq, setMaxMoq] = useState("");

  const [run, setRun] = useState<SearchRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);

  const product = products.find((p) => p.id === productId);

  const filters = useMemo<QuoteFilters>(
    () => ({
      maxUnitPrice: parseLimit(maxUnitPrice),
      maxLeadTimeDays: parseLimit(maxLeadTime),
      maxMoq: parseLimit(maxMoq),
    }),
    [maxUnitPrice, maxLeadTime, maxMoq],
  );
  const filtersActive = Object.values(filters).some((v) => v !== undefined);

  const allQuotes = useMemo(() => (run ? sortByLandedCost(run.quotes) : []), [run]);
  const shown = useMemo(() => applyFilters(allQuotes, filters), [allQuotes, filters]);
  const distinctions = useMemo(() => distinctionsFor(shown), [shown]);

  // Si el proveedor elegido queda fuera de los filtros, la selección cae en el primero visible.
  const selected = shown.find((q) => q.id === selectedId) ?? shown[0];
  const compared = shown.find((q) => q.id === compareId && q.id !== selected?.id);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!product) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createSourcingRun({
        product_id: product.id,
        category: product.category,
        destination_region: destinationRegion,
        max_results: maxResults,
      });
      setRun({ quotes: result.quotes, destinationRegion, ranAt: new Date() });
      setSelectedId(null);
      setCompareId(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La búsqueda de proveedores falló.");
    } finally {
      setSubmitting(false);
    }
  }

  function changeProduct(id: string) {
    setProductId(id);
    setChangingProduct(false);
    setRun(null);
    setSelectedId(null);
    setCompareId(null);
    setError(null);
  }

  function clearFilters() {
    setMaxUnitPrice("");
    setMaxLeadTime("");
    setMaxMoq("");
  }

  function analyzeEconomics(quote: SupplierQuote) {
    const params = new URLSearchParams({ product_id: quote.product_id, supplier_quote_id: quote.id });
    router.push(`/economics?${params.toString()}`);
  }

  function validateWithSupplier(quote: SupplierQuote) {
    const params = new URLSearchParams({
      title: `Validar abastecimiento con ${quoteName(quote)} para ${product?.name ?? quote.product_id}`,
      unit_cost: String(quote.unit_price),
      lead_time_days: String(quote.lead_time_days),
      supplier_verified: String(quote.verified),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function toggleCompare(quote: SupplierQuote) {
    setCompareId((current) => (current === quote.id ? null : quote.id));
  }

  // --- Mapa: un punto por región de origen presente en los resultados + el destino ---
  const { mapPoints, mapRoutes, unmapped } = useMemo(() => {
    if (!run) return { mapPoints: [] as MapPoint[], mapRoutes: [] as MapRoute[], unmapped: [] as string[] };
    const destination = run.destinationRegion;
    const origins = [...new Set(shown.map(quoteRegion).filter((r): r is string => Boolean(r)))];
    const regions = [...new Set([...origins, destination])];
    const points: MapPoint[] = [];
    const missing: string[] = [];
    for (const region of regions) {
      const lonLat = REGION_ANCHORS[region];
      if (!lonLat) {
        missing.push(region);
        continue;
      }
      const isOrigin = origins.includes(region);
      points.push({
        id: region,
        label: regionLabel(region),
        lonLat,
        kind: region === destination ? (isOrigin ? "both" : "destination") : "origin",
      });
    }
    const routes: MapRoute[] = origins
      .filter((o) => o !== destination && REGION_ANCHORS[o] && REGION_ANCHORS[destination])
      .map((o) => ({ id: `${o}->${destination}`, from: o, to: destination }));
    return { mapPoints: points, mapRoutes: routes, unmapped: missing };
  }, [run, shown]);

  function selectRegion(region: string) {
    const inRegion = shown.find((q) => quoteRegion(q) === region);
    if (inRegion) setSelectedId(inRegion.id);
  }

  const tableColumns: DataTableColumn<SupplierQuote>[] = [
    {
      key: "name",
      header: "Proveedor",
      cell: (q) => <span className="font-medium">{quoteName(q)}</span>,
      sortValue: quoteName,
      exportValue: quoteName,
    },
    {
      key: "region",
      header: "Origen",
      cell: (q) => regionLabel(quoteRegion(q)),
      sortValue: (q) => regionLabel(quoteRegion(q)),
      exportValue: (q) => regionLabel(quoteRegion(q)),
    },
    {
      key: "unit_price",
      header: "Precio",
      align: "right",
      cell: (q) => formatAmount(q.unit_price),
      sortValue: (q) => q.unit_price,
      exportValue: (q) => q.unit_price,
    },
    {
      key: "moq",
      header: "MOQ",
      align: "right",
      cell: (q) => formatInteger(q.moq),
      sortValue: (q) => q.moq,
      exportValue: (q) => q.moq,
    },
    {
      key: "lead_time",
      header: "Entrega",
      align: "right",
      cell: (q) => `${q.lead_time_days} días`,
      sortValue: (q) => q.lead_time_days,
      exportValue: (q) => q.lead_time_days,
    },
    {
      key: "logistics",
      header: "Logística",
      align: "right",
      cell: (q) => formatAmount(q.logistics_cost_per_unit),
      sortValue: (q) => q.logistics_cost_per_unit,
      exportValue: (q) => q.logistics_cost_per_unit,
    },
    {
      key: "landed",
      header: "Coste entregado",
      align: "right",
      cell: (q) => <span className="font-semibold text-primary">{formatAmount(q.total_landed_cost_per_unit)}</span>,
      sortValue: (q) => q.total_landed_cost_per_unit,
      exportValue: (q) => q.total_landed_cost_per_unit,
    },
    {
      key: "verified",
      header: "Verificación",
      cell: (q) => <VerificationChip verified={q.verified} />,
      sortValue: (q) => Number(q.verified),
      exportValue: (q) => (q.verified ? "Sí" : "No"),
    },
    {
      key: "reliability",
      header: "Fiabilidad",
      align: "right",
      cell: (q) => `${Math.round(q.reliability_score * 100)}%`,
      sortValue: (q) => q.reliability_score,
      exportValue: (q) => Math.round(q.reliability_score * 100),
    },
    {
      key: "actions",
      header: "Acciones",
      cell: (q) => (
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            title="Analizar economía"
            aria-label={`Analizar economía de ${quoteName(q)}`}
            onClick={() => analyzeEconomics(q)}
          >
            <Calculator />
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            title="Validar con el Director ejecutivo"
            aria-label={`Validar con el Director ejecutivo a ${quoteName(q)}`}
            onClick={() => validateWithSupplier(q)}
          >
            <Brain />
          </Button>
        </div>
      ),
    },
  ];

  if (products.length === 0 || !product) {
    return (
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
    );
  }

  const radarSeries: RadarSeries[] = selected
    ? [
        { label: quoteName(selected), color: "var(--emerald-bright)", values: supplierRadarValues(selected, shown) },
        compared
          ? { label: quoteName(compared), color: "var(--text-secondary)", values: supplierRadarValues(compared, shown) }
          : { label: "Media de los encontrados", color: "var(--text-secondary)", values: averageRadarValues(shown) },
      ]
    : [];

  const verifiedCount = shown.filter((q) => q.verified).length;
  const maxMoqLimit = filters.maxMoq;
  const top3 = shown.slice(0, 3);

  return (
    <div className="space-y-6">
      <form id="sourcing-form" onSubmit={handleSubmit} className="grid gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5">
          <CardHeader>
            <CardTitle>Producto seleccionado</CardTitle>
            <CardAction>
              <Button type="button" variant="ghost" size="xs" onClick={() => setChangingProduct((v) => !v)}>
                Cambiar
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            {changingProduct ? (
              <Field label="Producto" htmlFor="sourcing-product">
                <select
                  id="sourcing-product"
                  value={productId}
                  onChange={(e) => changeProduct(e.target.value)}
                  className={INPUT_CLASS}
                >
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.category}
                    </option>
                  ))}
                </select>
              </Field>
            ) : null}

            <div className="flex items-center gap-4">
              <div className="flex size-20 shrink-0 items-center justify-center rounded-xl border bg-muted text-primary">
                <PackageSearch className="size-8" />
              </div>
              <div className="min-w-0 space-y-2">
                <p className="truncate text-base font-semibold">{product.name}</p>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline">{product.category}</Badge>
                  <Badge variant="outline">{PRODUCT_STATUS_LABEL[product.status] ?? product.status}</Badge>
                  <Badge variant="outline">{PRODUCT_SOURCE_LABEL[product.source] ?? product.source}</Badge>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t pt-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Investigación:</span>
                <DataProvenanceBadge
                  status="pending"
                  tooltip="El backend no expone el score de investigación de un producto (solo dentro de la propia ejecución de Investigación)."
                />
              </span>
              <span className="flex items-center gap-1.5">
                <span className="text-muted-foreground">Mercado objetivo:</span>
                <span className="font-medium text-primary">{regionLabel(destinationRegion)}</span>
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-4">
          <CardHeader>
            <CardTitle>Parámetros de búsqueda</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Región de destino" htmlFor="sourcing-destination">
                <select
                  id="sourcing-destination"
                  value={destinationRegion}
                  onChange={(e) => setDestinationRegion(e.target.value)}
                  className={INPUT_CLASS}
                >
                  {DESTINATION_REGIONS.map((region) => (
                    <option key={region} value={region}>
                      {REGION_LABELS[region]}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Resultados máximos" htmlFor="sourcing-max-results">
                <input
                  id="sourcing-max-results"
                  type="number"
                  min={1}
                  max={20}
                  value={maxResults}
                  onChange={(e) => setMaxResults(Number(e.target.value))}
                  className={INPUT_CLASS}
                />
              </Field>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">Filtrar los resultados</p>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Precio máx." htmlFor="sourcing-max-price">
                  <input
                    id="sourcing-max-price"
                    type="number"
                    min={0}
                    step="0.01"
                    value={maxUnitPrice}
                    onChange={(e) => setMaxUnitPrice(e.target.value)}
                    placeholder="—"
                    className={INPUT_CLASS}
                  />
                </Field>
                <Field label="Plazo máx. (días)" htmlFor="sourcing-max-lead">
                  <input
                    id="sourcing-max-lead"
                    type="number"
                    min={0}
                    value={maxLeadTime}
                    onChange={(e) => setMaxLeadTime(e.target.value)}
                    placeholder="—"
                    className={INPUT_CLASS}
                  />
                </Field>
                <Field label="MOQ máx." htmlFor="sourcing-max-moq">
                  <input
                    id="sourcing-max-moq"
                    type="number"
                    min={0}
                    value={maxMoq}
                    onChange={(e) => setMaxMoq(e.target.value)}
                    placeholder="—"
                    className={INPUT_CLASS}
                  />
                </Field>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 border-t pt-3">
              <span className="text-xs text-muted-foreground">Filtros avanzados</span>
              <DataProvenanceBadge
                status="pending"
                tooltip="El backend de abastecimiento solo admite categoría, región de destino y nº de resultados. Estos filtros necesitarían campos que hoy no existen."
              />
              {ADVANCED_FILTERS.map((label) => (
                <Button key={label} type="button" size="xs" variant="outline" disabled>
                  {label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>Resumen de la búsqueda</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <Stat value={run ? allQuotes.length : "—"} label="Analizados" />
              <Stat value={run ? shown.length : "—"} label="Preseleccionados" />
              <Stat value={run ? verifiedCount : "—"} label="Verificados" />
              <Stat value={run ? allQuotes.length - shown.length : "—"} label="Descartados por filtros" />
            </div>
            {run ? (
              <p className="text-[11px] text-muted-foreground">
                Ejecutada a las {run.ranAt.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}
              </p>
            ) : null}
            <Button type="submit" size="lg" className="w-full" disabled={submitting}>
              {submitting ? <Loader2 className="animate-spin" /> : <Search />}
              {submitting ? "Buscando…" : "Buscar proveedores"}
            </Button>
          </CardContent>
        </Card>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>La búsqueda de proveedores falló</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {submitting ? (
        <div className="grid gap-4 xl:grid-cols-12" aria-busy="true" aria-label="Buscando proveedores">
          <Skeleton className="h-80 xl:col-span-6" />
          <Skeleton className="h-80 xl:col-span-6" />
          <Skeleton className="h-64 xl:col-span-12" />
        </div>
      ) : !run ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Truck}
              title="Sin búsqueda de proveedores todavía"
              description="Elige la región de destino y pulsa «Buscar proveedores» para ver aquí las cotizaciones ordenadas por coste total de entrega."
            />
          </CardContent>
        </Card>
      ) : allQuotes.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Truck}
              title={`No se encontraron proveedores para «${product.category}»`}
              description="El directorio de proveedores no tiene candidatos para esta categoría."
            />
          </CardContent>
        </Card>
      ) : shown.length === 0 || !selected ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={Truck}
              title="Ningún proveedor cumple los filtros"
              description={`Se encontraron ${allQuotes.length} proveedores, pero todos quedan fuera de los límites que has fijado.`}
              action={
                filtersActive ? (
                  <Button type="button" size="sm" variant="outline" onClick={clearFilters}>
                    Limpiar filtros
                  </Button>
                ) : undefined
              }
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <section className="grid gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-6">
              <CardHeader>
                <CardTitle>Proveedores recomendados</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Directorio de proveedores simulado (MockSupplierDirectory): precios, MOQ, plazos y fiabilidad son valores de prueba, sin fuente real todavía."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Los {top3.length} con menor coste total de entrega
                  {shown.length > 3 ? ` (de ${shown.length})` : ""}, para {regionLabel(run.destinationRegion)}. Importes por
                  unidad.
                </p>
                <div className="grid gap-3 sm:grid-cols-3">
                  {top3.map((quote, index) => (
                    <SupplierCard
                      key={quote.id}
                      quote={quote}
                      rank={index + 1}
                      distinctions={(distinctions.get(quote.id) ?? []).map((d) => DISTINCTION_LABEL[d])}
                      selected={selected.id === quote.id}
                      comparing={compared?.id === quote.id}
                      onSelect={() => setSelectedId(quote.id)}
                      onCompare={() => toggleCompare(quote)}
                      onAnalyze={() => analyzeEconomics(quote)}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-6">
              <CardHeader>
                <CardTitle>Mapa de proveedores</CardTitle>
                <CardAction>
                  <DataProvenanceBadge
                    status="estimated"
                    tooltip="Las regiones son las del directorio simulado; el pin marca la región, no una ciudad concreta. Los costes y plazos son simulados."
                  />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-3">
                <RouteMap
                  points={mapPoints}
                  routes={mapRoutes}
                  selectedPointId={quoteRegion(selected)}
                  onSelectPoint={selectRegion}
                />
                <div className="grid gap-3 rounded-lg border bg-background/60 p-3 text-xs sm:grid-cols-3">
                  <div>
                    <p className="text-muted-foreground">Ruta seleccionada</p>
                    <p className="mt-0.5 font-medium">
                      {regionLabel(quoteRegion(selected))} → {regionLabel(run.destinationRegion)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Plazo del proveedor</p>
                    <p className="mt-0.5 font-medium">{selected.lead_time_days} días</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Coste logístico / unidad</p>
                    <p className="mt-0.5 font-medium">{formatAmount(selected.logistics_cost_per_unit)}</p>
                  </div>
                </div>
                {selected.data?.notes ? (
                  <p className="text-[11px] text-muted-foreground">Nota del backend: {selected.data.notes}</p>
                ) : null}
                {unmapped.length > 0 ? (
                  <p className="text-[11px] text-muted-foreground">
                    Sin coordenadas en el mapa: {unmapped.map(regionLabel).join(", ")}.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </section>

          <section className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Listado de proveedores</CardTitle>
                <CardAction>
                  <span className="text-xs text-muted-foreground">{shown.length} resultados</span>
                </CardAction>
              </CardHeader>
              <CardContent>
                <DataTable
                  columns={tableColumns}
                  rows={shown}
                  getRowId={(q) => q.id}
                  selectedId={selected.id}
                  onSelect={(q) => setSelectedId(q.id)}
                  getSearchText={(q) => `${quoteName(q)} ${regionLabel(quoteRegion(q))}`}
                  searchPlaceholder="Buscar proveedor…"
                  exportFileName={`proveedores-${product.name.toLowerCase().replace(/\s+/g, "-")}.csv`}
                  emptyMessage="Ningún proveedor coincide con la búsqueda."
                />
              </CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
              <Card>
                <CardHeader>
                  <CardTitle>Coste total estimado</CardTitle>
                  <CardAction>
                    <DataProvenanceBadge
                      status="estimated"
                      tooltip="Logística y aduana simuladas (no son tarifas reales de transportista ni de aduana)."
                    />
                  </CardAction>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="truncate text-xs text-muted-foreground">{quoteName(selected)}</p>
                  <dl className="space-y-2 text-sm">
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Precio del proveedor</dt>
                      <dd className="font-medium">{formatAmount(selected.unit_price)}</dd>
                    </div>
                    <div className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">Logística y aduana</dt>
                      <dd className="font-medium">{formatAmount(selected.logistics_cost_per_unit)}</dd>
                    </div>
                    <div className="flex justify-between gap-2 border-t pt-2">
                      <dt className="font-medium text-primary">Coste total estimado</dt>
                      <dd className="text-base font-semibold text-primary">
                        {formatAmount(selected.total_landed_cost_per_unit)}
                      </dd>
                    </div>
                  </dl>
                  <div
                    className="flex h-2 overflow-hidden rounded-full bg-panel-hover"
                    role="img"
                    aria-label={`Del coste total, ${Math.round((selected.unit_price / selected.total_landed_cost_per_unit) * 100)}% es precio del proveedor y el resto logística y aduana`}
                  >
                    <div
                      className="bg-primary"
                      style={{ width: `${(selected.unit_price / selected.total_landed_cost_per_unit) * 100}%` }}
                    />
                    <div className="ml-0.5 flex-1 bg-cyan-accent" />
                  </div>
                  <div className="flex justify-between text-[11px] text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-primary" />
                      Proveedor {Math.round((selected.unit_price / selected.total_landed_cost_per_unit) * 100)} %
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full bg-cyan-accent" />
                      Logística y aduana{" "}
                      {Math.round((selected.logistics_cost_per_unit / selected.total_landed_cost_per_unit) * 100)} %
                    </span>
                  </div>
                  <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
                    <DataProvenanceBadge
                      status="pending"
                      tooltip="Transporte, arancel, fulfillment, pago/divisa y reserva de devoluciones (parte de la spec §6.8) no se desglosan: el backend solo aporta logística + aduana agregadas."
                    />
                    <span>Desglose completo pendiente. Importes sin divisa: el backend no especifica moneda.</span>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Compatibilidad con Amazona</CardTitle>
                  <CardAction>
                    <DataProvenanceBadge
                      status="pending"
                      tooltip="Solo 2 de los 9 criterios de la spec (§6.9) tienen dato en el backend."
                    />
                  </CardAction>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-2">
                    <CompatibilityRow
                      state={selected.verified ? "pass" : "fail"}
                      label="Proveedor verificado"
                    />
                    {maxMoqLimit !== undefined ? (
                      <CompatibilityRow
                        state={selected.moq <= maxMoqLimit ? "pass" : "fail"}
                        label={`MOQ dentro de tu límite (≤ ${formatInteger(maxMoqLimit)})`}
                        detail={`${formatInteger(selected.moq)} uds`}
                      />
                    ) : (
                      <CompatibilityRow
                        state="info"
                        label="MOQ (fija un MOQ máx. para evaluarlo)"
                        detail={`${formatInteger(selected.moq)} uds`}
                      />
                    )}
                    {PENDING_COMPATIBILITY.map((label) => (
                      <CompatibilityRow key={label} state="pending" label={label} />
                    ))}
                  </ul>
                </CardContent>
              </Card>

              <Card className="lg:col-span-2 xl:col-span-1">
                <CardHeader>
                  <CardTitle>Score de proveedor</CardTitle>
                  <CardAction>
                    <DataProvenanceBadge
                      status="estimated"
                      tooltip="Ejes relativos al conjunto encontrado: 100 % = el mejor proveedor de la búsqueda en precio, logística, MOQ y plazo. Fiabilidad es el valor nominal del directorio simulado."
                    />
                  </CardAction>
                </CardHeader>
                <CardContent className="space-y-2">
                  <RadarChart axes={[...SUPPLIER_RADAR_AXES]} series={radarSeries} />
                  <div className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
                    <DataProvenanceBadge
                      status="pending"
                      tooltip="Calidad, compliance y escalabilidad (spec §6.10) no tienen dato en el backend."
                    />
                    <span>Calidad, compliance y escalabilidad: pendientes de dato real.</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </section>
        </>
      )}

      <NextStepBar
        steps={[
          { label: "Proveedor seleccionado", icon: Truck, state: selected ? "done" : "current" },
          { label: "Análisis económico", icon: Calculator, state: selected ? "current" : "todo" },
          { label: "Revisión legal", icon: Scale, state: "todo" },
          { label: "Aprobación CEO", icon: Brain, state: "todo" },
          { label: "Integración operativa", icon: PackageCheck, state: "todo" },
        ]}
        action={
          <Button type="button" disabled={!selected} onClick={() => selected && analyzeEconomics(selected)}>
            Enviar a análisis económico
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
