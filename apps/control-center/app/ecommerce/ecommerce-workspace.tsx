"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  CircleCheck,
  ClipboardCheck,
  FlaskConical,
  Globe,
  Loader2,
  Megaphone,
  PackageSearch,
  Plus,
  Rocket,
  Search,
  ShoppingBag,
  Store,
  Truck,
  Video,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, type Product, type Storefront } from "@/lib/api";
import { DEMO_SALE, DEMO_UNIT_COSTS } from "@/lib/demo/economics";
import { demoQuotes, demoSupplierProfile } from "@/lib/demo/sourcing";
import {
  CHECKOUT_MODES,
  DEMO_COMPARE_AT_FACTOR,
  DEMO_FEATURES,
  DEMO_QUALITY,
  PAYMENT_METHODS,
  demoMasterData,
  demoSku,
} from "@/lib/demo/storefront";
import { contentChecklist, launchReadiness } from "@/lib/ecommerce";
import { dedupeQuotesBySupplier } from "@/lib/economics";
import { formatEuro, formatInteger, formatPercent } from "@/lib/format";
import { buildLegalView } from "@/lib/legal-view";
import { latestForMarket } from "@/lib/markets";
import type { ProductChannelData } from "@/lib/product-channels";
import { buildRows } from "@/lib/research-view";
import { rankSuppliers } from "@/lib/sourcing-view";
import {
  channelCards,
  marketConfig,
  purchaseFunnel,
  readinessRatio,
  storeQuality,
  type ChannelCardView,
  type ChannelTone,
} from "@/lib/storefront-view";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { Flag, type FlagCode } from "@/components/flag";
import { HeaderClock } from "@/components/header-clock";
import { HeaderTile } from "@/components/header-tile";
import { InfoTile } from "@/components/info-tile";
import { LevelChip } from "@/components/level-chip";
import { NextStepBar } from "@/components/next-step-bar";
import { PageHeader } from "@/components/page-header";
import { ProductSummary } from "@/components/product-summary";
import { RingGauge } from "@/components/ring-gauge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { AmazonPanels } from "./amazon-panels";
import { ECOMMERCE_DESCRIPTION, ECOMMERCE_TITLE } from "./copy";
import { StoreBuilder, type BuilderTab, type StoreContent } from "./store-builder";

const MARKETS = [
  { value: "eu", label: "España + UE", flags: ["es", "eu"] as FlagCode[] },
  { value: "us", label: "Estados Unidos", flags: [] as FlagCode[] },
  { value: "mx", label: "México", flags: ["mx"] as FlagCode[] },
];

const CHANNEL_ICON: Record<ChannelCardView["key"], LucideIcon> = {
  store: Globe,
  amazon: ShoppingBag,
  google: Search,
  tiktok: Video,
};

const TONE_BAR: Record<ChannelTone, string> = {
  ok: "bg-primary",
  warn: "bg-primary",
  bad: "bg-destructive",
  neutral: "bg-primary",
};

function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

/** Contenido del escaparate: el copy del borrador real o, si no lo hay, uno de ejemplo. */
function contentFrom(storefront: Storefront | undefined, product: Product): StoreContent {
  const copy = storefront?.data?.landing_page_copy;
  const demoFeatures = DEMO_FEATURES.map((f) => `${f.title} ${f.detail}`);
  if (!copy) {
    return {
      title: product.name,
      subtitle: "Diseñado para el día a día, con calidad verificada por AMAZONA.",
      features: demoFeatures,
      cta: "Comprar ahora",
    };
  }
  const bullets = copy.bullets ?? [];
  return {
    title: copy.headline || product.name,
    subtitle: copy.subheadline,
    features: [...bullets, ...demoFeatures].slice(0, 4),
    cta: copy.cta || "Comprar ahora",
  };
}

export function EcommerceWorkspace({
  products,
  productId,
  data,
  initialMarket,
}: {
  products: Product[];
  productId?: string;
  data: ProductChannelData;
  initialMarket: string;
}) {
  const router = useRouter();
  const product = products.find((p) => p.id === productId);

  const [market, setMarket] = useState(MARKETS.some((m) => m.value === initialMarket) ? initialMarket : "eu");
  const [tab, setTab] = useState<BuilderTab>("preview");
  const [content, setContent] = useState<StoreContent | null>(null);
  const [checkoutMode, setCheckoutMode] = useState(CHECKOUT_MODES[0].value);
  const [methods, setMethods] = useState(() => new Set(PAYMENT_METHODS.filter((m) => m.enabled).map((m) => m.key)));
  const [amazonOpen, setAmazonOpen] = useState(false);
  const [generating, setGenerating] = useState<"store" | "amazon" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (products.length === 0 || !product) {
    return (
      <div>
        <PageHeader title={ECOMMERCE_TITLE} description={ECOMMERCE_DESCRIPTION} />
        <Card>
          <CardContent>
            <EmptyState
              icon={PackageSearch}
              title="Aún no hay productos que vender"
              description="La tienda parte de un producto investigado, con sus análisis económico y legal."
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

  const marketInfo = MARKETS.find((m) => m.value === market) ?? MARKETS[0];
  const storefront = latestForMarket(data.storefronts, market);
  const listing = latestForMarket(data.listings, market);
  const legal = latestForMarket(data.legal, market);
  const economic = data.economics[0];

  const legalView = buildLegalView(market, legal);
  const researchScore = buildRows([product], [])[0].score;
  const approvedPrice = economic?.sale_price ?? DEMO_SALE.salePrice;
  const supplierQuote =
    (economic ? data.quotes.find((q) => q.id === economic.supplier_quote_id) : undefined) ??
    rankSuppliers(data.quotes.length ? dedupeQuotesBySupplier(data.quotes) : demoQuotes(product.id))[0]?.quote;
  const supplierProfile = supplierQuote ? demoSupplierProfile(supplierQuote) : undefined;

  const storeContent = content ?? contentFrom(storefront, product);
  const price = storefront?.data?.catalog_entry?.price ?? approvedPrice;
  const compareAt = Math.floor(price * DEMO_COMPARE_AT_FACTOR) + 0.9;
  const slug = storefront?.store_slug ?? slugify(product.name);

  const readiness = launchReadiness({ economic, storefront, legal });
  const channels = channelCards({ storefront, listing, storeReadiness: readinessRatio(readiness) });
  const orders = economic?.data?.scenarios?.base?.monthly_unit_sales ?? DEMO_SALE.monthlyOrders;
  const funnel = purchaseFunnel(orders, DEMO_UNIT_COSTS.conversionPct);
  const quality = storeQuality(DEMO_QUALITY.content / 100, legalView.compliance.ratio);
  const checklist = contentChecklist(storefront ?? { data: null });
  const markets = marketConfig(approvedPrice, data.storefronts);
  const master = demoMasterData(product.id);
  const sku = storefront?.data?.catalog_entry?.sku ?? demoSku(product.category, product.id);
  const plan = storefront?.data?.payment_gateway_plan;
  const gateway = plan?.gateway ?? "stripe";

  const legalGate = {
    blocked: { label: "Bloqueado", icon: Ban, tone: "text-destructive" },
    review: { label: "Revisión humana", icon: AlertTriangle, tone: "text-warning" },
    ready: { label: "Aprobado", icon: CircleCheck, tone: "text-primary" },
  }[legalView.gate.state];

  function changeMarket(next: string) {
    setMarket(next);
    setContent(null);
  }

  function changeProduct(id: string) {
    router.push(`/ecommerce?${new URLSearchParams({ product_id: id, market }).toString()}`);
  }

  async function generateStore() {
    setError(null);
    setGenerating("store");
    try {
      const result = await api.createStorefrontRun({ product_id: product!.id, market });
      setContent(contentFrom(result, product!));
      setTab("preview");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La generación de la tienda falló.");
    } finally {
      setGenerating(null);
    }
  }

  async function generateListing() {
    setError(null);
    setGenerating("amazon");
    try {
      await api.createMarketplaceListingRun({ product_id: product!.id, market, platform: "amazon" });
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La generación del listado de Amazon falló.");
    } finally {
      setGenerating(null);
    }
  }

  function configure(key: ChannelCardView["key"]) {
    if (key === "store") {
      setTab("preview");
      document.getElementById("constructor")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (key === "amazon") {
      setAmazonOpen(true);
      setTimeout(() => document.getElementById("amazon")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  }

  function planMarketing() {
    router.push(`/marketing?${new URLSearchParams({ product_id: product!.id, market }).toString()}`);
  }

  function requestLaunchApproval() {
    const params = new URLSearchParams({
      title: `Aprobar lanzamiento de ${product!.name} en ${marketInfo.label}`,
      sale_price: String(price),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={ECOMMERCE_TITLE}
        description={ECOMMERCE_DESCRIPTION}
        actions={
          <>
            <DataProvenanceBadge
              status="demo"
              tooltip="Incluye datos de demostración: Google Shopping y TikTok Shop, el estado de Amazon si no hay listado, valoraciones, precio tachado, diseño, páginas, A/B testing, métodos de pago, embudo, calidad del escaparate (salvo la información legal), mercados europeos y la ficha maestra (EAN, peso, dimensiones). Real: borradores de tienda y de Amazon con su copy, estado, plan de pasarela y catálogo."
            />
            <HeaderClock />
            <HeaderTile
              label="Producto activo"
              value={product.id}
              options={products.map((p) => ({ value: p.id, label: p.name }))}
              onChange={changeProduct}
            />
          </>
        }
      />

      {/* Producto y contexto */}
      <Card>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-[minmax(0,1.7fr)_repeat(6,minmax(0,1fr))]">
          <div className="sm:col-span-2 lg:col-span-3 2xl:col-span-1">
            <ProductSummary product={product} />
          </div>
          <InfoTile label="Investigación">
            <p className="text-xl font-semibold text-primary">
              {researchScore}
              <span className="text-sm">/100</span>
            </p>
            <div className="mt-1.5 h-1.5 rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: `${researchScore}%` }} />
            </div>
          </InfoTile>
          <InfoTile label="Precio aprobado">
            <p className="text-xl font-semibold">{formatEuro(approvedPrice)}</p>
          </InfoTile>
          <InfoTile label="Proveedor">
            <p className="truncate text-sm font-medium">{supplierQuote?.data?.name ?? supplierQuote?.supplier_id ?? "—"}</p>
            {supplierProfile ? (
              <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Flag code={supplierProfile.flag} /> {supplierProfile.country}
              </p>
            ) : null}
          </InfoTile>
          <InfoTile label="Mercados objetivo">
            <select
              value={market}
              onChange={(e) => changeMarket(e.target.value)}
              aria-label="Mercado objetivo"
              className="w-full min-w-0 appearance-none truncate bg-transparent text-sm font-semibold outline-none"
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value} className="bg-popover">
                  {m.label}
                </option>
              ))}
            </select>
            <p className="mt-1.5 flex gap-1.5">
              {marketInfo.flags.map((f) => (
                <Flag key={f} code={f} />
              ))}
            </p>
          </InfoTile>
          <InfoTile label="Legal Gate">
            <Link href={`/legal?${new URLSearchParams({ product_id: product.id, market }).toString()}`} className={cn("flex items-center gap-1.5 font-semibold", legalGate.tone)}>
              <legalGate.icon className="size-5 shrink-0" /> {legalGate.label}
            </Link>
          </InfoTile>
          <InfoTile label="Modelo logístico">
            <p className="flex items-center gap-2 text-sm font-medium">
              <Truck className="size-5 shrink-0 text-primary" />
              <span>
                Envío directo <span className="block text-xs font-normal text-muted-foreground">(dropshipping)</span>
              </span>
            </p>
          </InfoTile>
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* Constructor · Canales · Checkout · Embudo */}
      <section className="grid gap-4 2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <StoreBuilder
          tab={tab}
          onTabChange={setTab}
          content={storeContent}
          onContentChange={setContent}
          price={price}
          compareAt={compareAt}
          slug={slug}
          generating={generating === "store"}
          onGenerate={() => void generateStore()}
        />

        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Canales de venta</CardTitle>
              <CardDescription>Configura y despliega el producto en los distintos canales.</CardDescription>
              <CardAction>
                <Button size="xs" variant="outline" className="text-primary" disabled title="Pendiente: el backend no permite añadir canales">
                  <Plus /> Añadir canal
                </Button>
              </CardAction>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
              {channels.map((c) => {
                const Icon = CHANNEL_ICON[c.key];
                const selected = (c.key === "store" && !amazonOpen) || (c.key === "amazon" && amazonOpen);
                return (
                  <div key={c.key} className={cn("flex min-w-0 flex-col gap-2 rounded-xl border bg-background/40 p-3", selected && "border-primary/60 bg-primary/5")}>
                    <p className="flex items-center gap-2 text-[13px] leading-tight font-semibold">
                      <Icon className="size-5 shrink-0 text-primary" />
                      <span className="line-clamp-2">{c.name}</span>
                    </p>
                    <LevelChip tone={c.tone} className="self-start">
                      {c.status}
                    </LevelChip>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-muted">
                        <div className={cn("h-full rounded-full", TONE_BAR[c.tone])} style={{ width: `${Math.round(c.readiness * 100)}%` }} />
                      </div>
                      <span className="text-xs font-medium tabular-nums">{formatPercent(c.readiness, 0)}</span>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => configure(c.key)}
                      disabled={c.key === "google" || c.key === "tiktok"}
                      title={c.key === "google" || c.key === "tiktok" ? `Pendiente: no hay integración con ${c.name}` : undefined}
                    >
                      Configurar
                    </Button>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-1 min-[112.5rem]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Checkout y pagos</CardTitle>
                <CardDescription>Métodos de pago y experiencia de compra.</CardDescription>
                <CardAction>
                  <span className="rounded-md border px-2 py-0.5 text-[10px] text-muted-foreground">
                    Powered by <span className="text-sm font-semibold text-sky-400">{gateway}</span>
                  </span>
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <fieldset className="space-y-1.5">
                  <legend className="mb-1 text-xs text-muted-foreground">Modo de checkout</legend>
                  {CHECKOUT_MODES.map((mode) => (
                    <label key={mode.value} className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="checkout-mode"
                        value={mode.value}
                        checked={checkoutMode === mode.value}
                        onChange={() => setCheckoutMode(mode.value)}
                        className="accent-primary"
                      />
                      {mode.label}
                    </label>
                  ))}
                </fieldset>
                <fieldset>
                  <legend className="mb-1.5 text-xs text-muted-foreground">Métodos de pago</legend>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                    {PAYMENT_METHODS.map((m) => (
                      <label key={m.key} className="flex items-center gap-2 text-[13px]">
                        <input
                          type="checkbox"
                          checked={methods.has(m.key)}
                          onChange={(e) =>
                            setMethods((current) => {
                              const next = new Set(current);
                              if (e.target.checked) next.add(m.key);
                              else next.delete(m.key);
                              return next;
                            })
                          }
                          className="accent-primary"
                        />
                        {m.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <p className="flex items-center gap-1.5 text-[11px] text-warning">
                  <FlaskConical className="size-3.5" />
                  {plan ? `Modo ${plan.mode === "test" ? "prueba" : plan.mode}` : "Modo prueba"} · salir en vivo requiere aprobación humana
                </p>
                <Button size="sm" variant="outline" className="w-full" onClick={() => configure("store")}>
                  Ver vista previa
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>
                  Funnel de compra <span className="font-normal text-muted-foreground">(estimado)</span>
                </CardTitle>
                <CardDescription>Conversión prevista con los supuestos de Economía.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <ul className="space-y-2.5 text-sm">
                  {funnel.steps.map((s) => (
                    <li key={s.label} className="grid grid-cols-[6rem_1fr_3.5rem] items-center gap-2">
                      <span className="text-muted-foreground">{s.label}</span>
                      <span className="h-2 rounded-full bg-muted">
                        <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(3, (s.value / (funnel.steps[0].value || 1)) * 100)}%` }} />
                      </span>
                      <span className="text-right font-medium tabular-nums">{formatInteger(s.value)}</span>
                    </li>
                  ))}
                </ul>
                <div className="rounded-lg border bg-background/40 p-3">
                  <p className="flex items-center justify-between text-sm">
                    Conversión estimada <span className="text-lg font-semibold text-primary">{formatPercent(funnel.conversion)}</span>
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">Compras = pedidos del escenario base de Economía.</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Calidad · Contenido · Mercados · Producto maestro */}
      <section className="grid gap-4 md:grid-cols-2 min-[112.5rem]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,0.95fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Calidad del escaparate</CardTitle>
            <CardDescription>Optimización y preparación para la conversión.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-4">
            <RingGauge value={quality.score / 100} size={104} centerLabel={`${quality.score}/100`} caption={quality.label} />
            <ul className="min-w-0 flex-1 space-y-1.5 text-xs">
              {quality.axes.map((a) => (
                <li key={a.label} className="grid grid-cols-[minmax(0,7.5rem)_1fr_1.75rem] items-center gap-2">
                  <span className="truncate text-muted-foreground">{a.label}</span>
                  <span className="h-1.5 rounded-full bg-muted">
                    <span className={cn("block h-full rounded-full", a.value >= 70 ? "bg-primary" : a.value >= 50 ? "bg-warning" : "bg-destructive")} style={{ width: `${a.value}%` }} />
                  </span>
                  <span className="text-right tabular-nums">{a.value}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Contenido generado por IA</CardTitle>
            <CardDescription>{storefront ? "Borrador generado por el agente de tienda." : "Contenido de ejemplo: genera la tienda con IA."}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="space-y-1.5 text-[13px]">
              {checklist.map((item) => (
                <li key={item.label} className="flex items-center gap-2" title={item.generated ? "Generado por el agente" : "De ejemplo: el generador aún no lo produce"}>
                  <CheckCircle2 className={cn("size-4 shrink-0", item.generated ? "text-primary" : "text-primary/45")} />
                  {item.label}
                </li>
              ))}
            </ul>
            <div className="grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={() => {
                  configure("store");
                  setTab("content");
                }}>
                Revisar contenido
              </Button>
              <Button size="sm" variant="outline" className="text-primary" onClick={() => void generateStore()} disabled={generating !== null}>
                {generating === "store" ? <Loader2 className="animate-spin" /> : null} Regenerar con IA
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Configuración por mercado</CardTitle>
            <CardDescription>Precio, idioma y disponibilidad por país o región.</CardDescription>
            <CardAction>
              <Button size="xs" variant="outline" className="text-primary" disabled title="Pendiente: el backend solo genera tiendas para UE, EE. UU. y México">
                <Plus /> Añadir mercado
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="pb-2 font-medium">Mercado</th>
                  <th className="pb-2 font-medium">Precio</th>
                  <th className="pb-2 font-medium">Idioma</th>
                  <th className="pb-2 font-medium">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {markets.map((m) => (
                  <tr key={m.key}>
                    <td className="py-2">
                      <span className="flex items-center gap-2 whitespace-nowrap">
                        {m.flag ? <Flag code={m.flag as FlagCode} /> : <Globe className="size-4 text-muted-foreground" />} {m.country}
                      </span>
                    </td>
                    <td className="py-2 tabular-nums whitespace-nowrap">{m.price !== null ? formatEuro(m.price) : "—"}</td>
                    <td className="py-2">{m.language}</td>
                    <td className="py-2">
                      <LevelChip tone={m.tone}>{m.status}</LevelChip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Producto maestro</CardTitle>
            <CardDescription>Información central sincronizada en todos los canales.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <dl className="space-y-1.5 text-[13px]">
              {[
                ["SKU", sku],
                ["EAN", master.ean],
                ["Peso", `${master.weightKg.toLocaleString("es-ES")} kg`],
                ["Dimensiones", master.dimensions],
                ["Stock proveedor", "Disponible"],
                ["Plazo entrega", supplierProfile ? `${supplierProfile.delivery[0]} – ${supplierProfile.delivery[1]} días` : "—"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className={cn("text-right font-medium", (label === "Stock proveedor" || label === "Plazo entrega") && "text-primary")}>{value}</dd>
                </div>
              ))}
            </dl>
            <Button size="sm" variant="outline" className="w-full text-primary" nativeButton={false} render={<Link href={`/sourcing?product_id=${product.id}`} />}>
              Ver y editar ficha del producto
            </Button>
          </CardContent>
        </Card>
      </section>

      {amazonOpen ? (
        <section id="amazon" className="scroll-mt-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <ShoppingBag className="size-5 text-primary" /> Amazon — {marketInfo.label}
            </h2>
            <Button size="sm" variant="ghost" onClick={() => setAmazonOpen(false)}>
              Cerrar
            </Button>
          </div>
          {listing ? (
            <AmazonPanels listing={listing} onPlanMarketing={planMarketing} />
          ) : (
            <Card>
              <CardContent>
                <EmptyState
                  icon={ShoppingBag}
                  title={`Sin listado de Amazon en ${marketInfo.label}`}
                  description="Genera el listado para ver el contenido, la competencia y las comisiones del canal."
                  action={
                    <Button size="sm" onClick={() => void generateListing()} disabled={generating !== null}>
                      {generating === "amazon" ? <Loader2 className="animate-spin" /> : <ShoppingBag />} Generar listado
                    </Button>
                  }
                />
              </CardContent>
            </Card>
          )}
        </section>
      ) : null}

      <NextStepBar
        steps={[
          { label: "Escaparate preparado", icon: Store, state: storefront ? "done" : "current" },
          { label: "Revisión de marketing", icon: Megaphone, state: storefront ? "current" : "todo" },
          { label: "Pruebas y optimización", icon: ClipboardCheck, state: "todo" },
          { label: "Aprobación de lanzamiento", icon: CircleCheck, state: "todo" },
          { label: "Despliegue en canales", icon: Rocket, state: "todo" },
        ]}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={planMarketing}>
              <Megaphone /> Plan de marketing
            </Button>
            <Button onClick={requestLaunchApproval}>
              Solicitar aprobación de lanzamiento <ArrowRight />
            </Button>
          </div>
        }
      />
    </div>
  );
}
