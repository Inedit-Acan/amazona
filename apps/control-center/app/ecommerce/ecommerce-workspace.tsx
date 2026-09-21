"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Calculator,
  Globe,
  Loader2,
  Megaphone,
  PackageSearch,
  Rocket,
  Scale,
  Search,
  ShoppingBag,
  Store,
  Video,
  type LucideIcon,
} from "lucide-react";
import { ApiError, api, type Product } from "@/lib/api";
import { formatAmount } from "@/lib/format";
import { legalGate } from "@/lib/legal";
import { MARKET_LABELS, latestForMarket, marketLabel } from "@/lib/markets";
import { EMPTY_PRODUCT_CHANNEL_DATA, loadProductChannelData, type ProductChannelData } from "@/lib/product-channels";
import { regionLabel } from "@/lib/regions";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { EmptyState } from "@/components/empty-state";
import { NextStepBar } from "@/components/next-step-bar";
import { ProductHeader } from "@/components/product-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { AmazonPanels } from "./amazon-panels";
import { StorePanels } from "./store-panels";

const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";

type Channel = "own-store" | "amazon";

const PENDING_CHANNELS: { icon: LucideIcon; name: string }[] = [
  { icon: Search, name: "Google Shopping" },
  { icon: Video, name: "TikTok Shop" },
];

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

function ContextItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1 rounded-lg border bg-background/50 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  );
}

function ChannelCard({
  icon: Icon,
  name,
  selected,
  onSelect,
  status,
  action,
  disabled = false,
}: {
  icon: LucideIcon;
  name: string;
  selected?: boolean;
  onSelect?: () => void;
  status: React.ReactNode;
  action: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border p-3",
        selected ? "border-primary bg-primary/5 shadow-[0_0_18px_-8px_var(--emerald)]" : "bg-background/40",
        disabled && "border-dashed opacity-80",
      )}
    >
      {onSelect ? (
        <button
          type="button"
          onClick={onSelect}
          aria-pressed={selected}
          className="flex items-center gap-2 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Icon className="size-5 shrink-0 text-primary" />
          <span className="text-sm font-semibold">{name}</span>
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <Icon className="size-5 shrink-0 text-muted-foreground" />
          <span className="text-sm font-semibold">{name}</span>
        </div>
      )}
      <div className="flex min-h-6 items-center">{status}</div>
      {action}
    </div>
  );
}

export function EcommerceWorkspace({
  products,
  initialProductId,
  initialData,
  initialMarket,
  initialChannel,
}: {
  products: Product[];
  initialProductId?: string;
  initialData: ProductChannelData;
  initialMarket: string;
  initialChannel: Channel;
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(initialProductId ?? "");
  const [data, setData] = useState(initialData);
  const [market, setMarket] = useState(initialMarket);
  const [channel, setChannel] = useState<Channel>(initialChannel);
  const [changingProduct, setChangingProduct] = useState(false);
  const [loadingProduct, setLoadingProduct] = useState(false);
  const [generating, setGenerating] = useState<Channel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latestProductRequest = useRef(initialProductId ?? "");

  const product = products.find((p) => p.id === productId);
  const storefront = latestForMarket(data.storefronts, market);
  const listing = latestForMarket(data.listings, market);
  const legal = latestForMarket(data.legal, market);
  const economic = data.economics[0];
  const economicQuote = economic ? data.quotes.find((q) => q.id === economic.supplier_quote_id) : undefined;

  async function changeProduct(id: string) {
    latestProductRequest.current = id;
    setProductId(id);
    setChangingProduct(false);
    setError(null);
    setLoadingProduct(true);
    try {
      const next = await loadProductChannelData(id);
      if (latestProductRequest.current !== id) return;
      setData(next);
      setMarket(next.storefronts[0]?.market ?? next.listings[0]?.market ?? market);
    } catch (err) {
      if (latestProductRequest.current !== id) return;
      setData(EMPTY_PRODUCT_CHANNEL_DATA);
      setError(err instanceof ApiError ? err.detail : "No se pudo cargar el estado de venta del producto.");
    } finally {
      if (latestProductRequest.current === id) setLoadingProduct(false);
    }
  }

  async function generate(target: Channel) {
    if (!product) return;
    setError(null);
    setGenerating(target);
    try {
      if (target === "own-store") {
        const result = await api.createStorefrontRun({ product_id: product.id, market });
        setData((current) => ({ ...current, storefronts: [result, ...current.storefronts] }));
      } else {
        const result = await api.createMarketplaceListingRun({ product_id: product.id, market, platform: "amazon" });
        setData((current) => ({ ...current, listings: [result, ...current.listings] }));
      }
      setChannel(target);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : target === "own-store"
            ? "La generación de la tienda falló."
            : "La generación del listado de marketplace falló.",
      );
    } finally {
      setGenerating(null);
    }
  }

  function planMarketing() {
    if (!product) return;
    router.push(`/marketing?${new URLSearchParams({ product_id: product.id, market }).toString()}`);
  }

  if (products.length === 0 || !product) {
    return (
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
    );
  }

  const gate = legal ? legalGate(legal.recommendation) : undefined;
  const hasAnyChannelContent = Boolean(storefront || listing);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Producto y contexto</CardTitle>
          <CardAction>
            <Button type="button" variant="ghost" size="xs" onClick={() => setChangingProduct((v) => !v)}>
              Cambiar producto
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-12">
            {changingProduct ? (
              <div className="md:col-span-2 xl:col-span-8">
                <Field label="Producto" htmlFor="ecommerce-product">
                  <select
                    id="ecommerce-product"
                    value={productId}
                    onChange={(e) => void changeProduct(e.target.value)}
                    className={INPUT_CLASS}
                  >
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.category}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            ) : null}
            <div className="md:col-span-2 xl:col-span-8">
              <ProductHeader product={product} />
            </div>
            <div className="md:col-span-2 xl:col-span-4">
              <Field label="Mercado" htmlFor="ecommerce-market">
                <select
                  id="ecommerce-market"
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  className={INPUT_CLASS}
                >
                  {Object.entries(MARKET_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </div>

          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <ContextItem label="Precio del análisis económico">
              {loadingProduct ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : economic ? (
                formatAmount(economic.sale_price)
              ) : (
                <Link href={`/economics?product_id=${product.id}`} className="text-xs font-normal text-primary underline">
                  Sin análisis económico
                </Link>
              )}
            </ContextItem>
            <ContextItem label="Proveedor">
              {loadingProduct ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : economicQuote ? (
                <>
                  <span className="block truncate">{economicQuote.data?.name ?? economicQuote.supplier_id}</span>
                  <span className="block text-xs font-normal text-muted-foreground">
                    {regionLabel(economicQuote.data?.region)}
                  </span>
                </>
              ) : (
                <span className="text-xs font-normal text-muted-foreground">Sin cotización analizada</span>
              )}
            </ContextItem>
            <ContextItem label="Mercado objetivo">{marketLabel(market)}</ContextItem>
            <ContextItem label="Legal Gate">
              {loadingProduct ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : gate ? (
                gate.title
              ) : (
                <Link href={`/legal?product_id=${product.id}`} className="text-xs font-normal text-primary underline">
                  Sin análisis legal en este mercado
                </Link>
              )}
            </ContextItem>
            <ContextItem label="Modelo logístico">
              <DataProvenanceBadge status="pending" tooltip="El backend no guarda el modelo logístico del producto." />
            </ContextItem>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Canales de venta</CardTitle>
          <CardAction>
            <DataProvenanceBadge
              status="pending"
              tooltip="El backend no calcula un % de readiness por canal ni permite añadir canales."
            />
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ChannelCard
              icon={Globe}
              name="Tienda propia"
              selected={channel === "own-store"}
              onSelect={() => setChannel("own-store")}
              status={
                storefront ? (
                  <StatusChip status={storefront.launch_status} />
                ) : (
                  <span className="text-xs text-muted-foreground">Sin generar en {marketLabel(market)}</span>
                )
              }
              action={
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={generating !== null || loadingProduct}
                  onClick={() => void generate("own-store")}
                >
                  {generating === "own-store" ? <Loader2 className="animate-spin" /> : <Store />}
                  {generating === "own-store" ? "Generando…" : storefront ? "Regenerar tienda" : "Generar tienda"}
                </Button>
              }
            />
            <ChannelCard
              icon={ShoppingBag}
              name="Amazon"
              selected={channel === "amazon"}
              onSelect={() => setChannel("amazon")}
              status={
                listing ? (
                  <StatusChip status={listing.listing_status} />
                ) : (
                  <span className="text-xs text-muted-foreground">Sin generar en {marketLabel(market)}</span>
                )
              }
              action={
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={generating !== null || loadingProduct}
                  onClick={() => void generate("amazon")}
                >
                  {generating === "amazon" ? <Loader2 className="animate-spin" /> : <ShoppingBag />}
                  {generating === "amazon" ? "Generando…" : listing ? "Regenerar listado" : "Generar listado"}
                </Button>
              }
            />
            {PENDING_CHANNELS.map((item) => (
              <ChannelCard
                key={item.name}
                icon={item.icon}
                name={item.name}
                disabled
                status={
                  <DataProvenanceBadge
                    status="pending"
                    tooltip={`No hay integración con ${item.name} en el backend.`}
                  />
                }
                action={
                  <Button type="button" size="sm" variant="outline" disabled>
                    Configurar
                  </Button>
                }
              />
            ))}
          </div>
          <p className="text-[11px] text-muted-foreground">
            Cada generación es un borrador simulado de {marketLabel(market)}: no publica nada en ningún canal.
          </p>
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {channel === "own-store" ? (
        storefront ? (
          <StorePanels
            storefront={storefront}
            storefronts={data.storefronts}
            legal={legal}
            economic={economic}
            onOptimizeAmazon={() => setChannel("amazon")}
          />
        ) : (
          <Card>
            <CardContent>
              <EmptyState
                icon={Store}
                title={`Sin tienda propia de este producto en ${marketLabel(market)}`}
                description="Pulsa «Generar tienda» en el canal para ver aquí la página de venta, el checkout y el estado de lanzamiento."
              />
            </CardContent>
          </Card>
        )
      ) : listing ? (
        <AmazonPanels listing={listing} onPlanMarketing={planMarketing} />
      ) : (
        <Card>
          <CardContent>
            <EmptyState
              icon={ShoppingBag}
              title={`Sin listado de Amazon de este producto en ${marketLabel(market)}`}
              description="Pulsa «Generar listado» en el canal para ver aquí el contenido, la competencia y las comisiones."
            />
          </CardContent>
        </Card>
      )}

      <NextStepBar
        steps={[
          { label: "Legal validado", icon: Scale, state: gate?.tone === "ok" ? "done" : "current" },
          { label: "Escaparate preparado", icon: Store, state: hasAnyChannelContent ? "done" : "todo" },
          { label: "Plan de marketing", icon: Megaphone, state: hasAnyChannelContent ? "current" : "todo" },
          { label: "Aprobación de lanzamiento", icon: Rocket, state: "todo" },
          { label: "Despliegue en canales", icon: Calculator, state: "todo" },
        ]}
        action={
          <Button type="button" disabled={!hasAnyChannelContent} onClick={planMarketing}>
            Planificar campaña de marketing
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
