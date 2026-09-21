"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Loader2,
  Megaphone,
  PackageSearch,
  Rocket,
  ShoppingBag,
  Truck,
  Wallet,
} from "lucide-react";
import { ApiError, api, type MarketingCampaign, type Product } from "@/lib/api";
import { formatAmount, formatPercent } from "@/lib/format";
import { legalGate } from "@/lib/legal";
import { campaignPlan, latestCampaign, platformLabel, PLATFORM_LABELS } from "@/lib/marketing";
import { MARKET_LABELS, latestForMarket, marketLabel } from "@/lib/markets";
import {
  EMPTY_PRODUCT_MARKETING_DATA,
  loadProductMarketingData,
  type ProductMarketingData,
} from "@/lib/product-channels";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { NextStepBar } from "@/components/next-step-bar";
import { ProductHeader } from "@/components/product-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CampaignPanels } from "./campaign-panels";

const INPUT_CLASS = "w-full rounded-md border bg-background px-3 py-2 text-sm";

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

function roasText(campaign: MarketingCampaign): string {
  const roas = campaign.data?.performance_estimate?.projected_roas;
  return roas == null ? "—" : `${formatAmount(roas)} x`;
}

export function MarketingWorkspace({
  products,
  initialProductId,
  initialData,
  initialMarket,
}: {
  products: Product[];
  initialProductId?: string;
  initialData: ProductMarketingData;
  initialMarket: string;
}) {
  const router = useRouter();

  const [productId, setProductId] = useState(initialProductId ?? "");
  const [data, setData] = useState(initialData);
  const [market, setMarket] = useState(initialMarket);
  const [platform, setPlatform] = useState(
    initialData.campaigns.find((c) => c.market === initialMarket)?.platform ?? "meta",
  );
  const [dailyBudget, setDailyBudget] = useState("20");
  const [changingProduct, setChangingProduct] = useState(false);
  const [loadingProduct, setLoadingProduct] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestProductRequest = useRef(initialProductId ?? "");

  const product = products.find((p) => p.id === productId);
  const campaign = latestCampaign(data.campaigns, market, platform);
  const plan = campaignPlan(data.campaigns, market);
  const economic = data.economics[0];
  const storefront = latestForMarket(data.storefronts, market);
  const listing = latestForMarket(data.listings, market);
  const legal = latestForMarket(data.legal, market);
  const gate = legal ? legalGate(legal.recommendation) : undefined;

  async function changeProduct(id: string) {
    latestProductRequest.current = id;
    setProductId(id);
    setChangingProduct(false);
    setError(null);
    setLoadingProduct(true);
    try {
      const next = await loadProductMarketingData(id);
      if (latestProductRequest.current !== id) return;
      setData(next);
      const nextMarket = next.campaigns[0]?.market ?? market;
      setMarket(nextMarket);
      setPlatform(next.campaigns.find((c) => c.market === nextMarket)?.platform ?? platform);
    } catch (err) {
      if (latestProductRequest.current !== id) return;
      setData(EMPTY_PRODUCT_MARKETING_DATA);
      setError(err instanceof ApiError ? err.detail : "No se pudo cargar el estado de marketing del producto.");
    } finally {
      if (latestProductRequest.current === id) setLoadingProduct(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!product) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createMarketingCampaignRun({
        product_id: product.id,
        market,
        platform,
        daily_budget: Number(dailyBudget),
      });
      setData((current) => ({ ...current, campaigns: [result, ...current.campaigns] }));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "La generación de la campaña falló.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateWithCeo() {
    if (!campaign) return;
    const params = new URLSearchParams({
      title: `Validar campaña de ${platformLabel(campaign.platform)} para el producto ${campaign.product_id}`,
      spend_amount: String(campaign.daily_budget),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function simulateOperations() {
    if (!product) return;
    router.push(`/operations?${new URLSearchParams({ product_id: product.id, market }).toString()}`);
  }

  if (products.length === 0 || !product) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            icon={PackageSearch}
            title="Aún no hay productos que promocionar"
            description="La campaña parte de un producto investigado, con sus análisis económico y legal."
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

  const planColumns: DataTableColumn<MarketingCampaign>[] = [
    {
      key: "platform",
      header: "Canal",
      cell: (row) => <span className="font-medium">{platformLabel(row.platform)}</span>,
      sortValue: (row) => row.platform,
    },
    { key: "budget", header: "Presupuesto diario", cell: (row) => formatAmount(row.daily_budget), sortValue: (row) => row.daily_budget },
    { key: "roas", header: "ROAS proyectado", cell: (row) => roasText(row) },
    { key: "status", header: "Estado", cell: (row) => <StatusChip status={row.campaign_status} /> },
  ];

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
                <Field label="Producto" htmlFor="marketing-product">
                  <select
                    id="marketing-product"
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
              <Field label="Mercado" htmlFor="marketing-market">
                <select
                  id="marketing-market"
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
            <ContextItem label="Margen de contribución">
              {loadingProduct ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : economic ? (
                formatPercent(economic.margin_percent)
              ) : (
                <span className="text-xs font-normal text-muted-foreground">Sin análisis económico</span>
              )}
            </ContextItem>
            <ContextItem label="CAC máximo">
              <DataProvenanceBadge status="pending" tooltip="El motor económico no calcula el CAC máximo tolerable." />
            </ContextItem>
            <ContextItem label="Landing">
              {loadingProduct ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : storefront ? (
                <StatusChip status={storefront.launch_status} />
              ) : (
                <Link
                  href={`/ecommerce?${new URLSearchParams({ product_id: product.id, market }).toString()}`}
                  className="text-xs font-normal text-primary underline"
                >
                  Sin tienda en {marketLabel(market)}
                </Link>
              )}
            </ContextItem>
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
          </dl>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-12">
        <form onSubmit={handleSubmit} className="xl:col-span-5">
          <Card className="h-full">
            <CardHeader>
              <CardTitle>Nueva campaña</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Canal" htmlFor="marketing-platform">
                  <select
                    id="marketing-platform"
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                    className={INPUT_CLASS}
                  >
                    {Object.entries(PLATFORM_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Presupuesto diario" htmlFor="marketing-budget">
                  <input
                    id="marketing-budget"
                    type="number"
                    step="0.01"
                    min={0}
                    required
                    value={dailyBudget}
                    onChange={(e) => setDailyBudget(e.target.value)}
                    className={INPUT_CLASS}
                  />
                </Field>
              </div>
              <p className="text-xs text-muted-foreground">
                El presupuesto es un supuesto tuyo; el rendimiento (CPC, CTR, conversión) es una estimación simulada
                por categoría y plataforma. Cambiar el canal muestra la propuesta de ese canal en {marketLabel(market)},
                si existe.
              </p>
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                <DataProvenanceBadge
                  status="pending"
                  tooltip="El agente de marketing solo acepta producto, mercado, plataforma y presupuesto diario."
                />
                Objetivo, evento de conversión, duración, CAC objetivo y CAC máximo: no configurables todavía.
              </div>
              <Button type="submit" size="lg" className="w-full" disabled={submitting || loadingProduct}>
                {submitting ? <Loader2 className="animate-spin" /> : <Megaphone />}
                {submitting ? "Generando…" : campaign ? "Regenerar propuesta" : "Generar propuesta de campaña"}
              </Button>
            </CardContent>
          </Card>
        </form>

        <Card className="xl:col-span-7">
          <CardHeader>
            <CardTitle>Plan de adquisición por canal</CardTitle>
            <CardAction>
              <DataProvenanceBadge
                status="estimated"
                tooltip="Una propuesta simulada por canal. El backend no reparte el presupuesto entre canales."
              />
            </CardAction>
          </CardHeader>
          <CardContent className="space-y-3">
            <DataTable
              columns={planColumns}
              rows={plan}
              getRowId={(row) => row.platform}
              selectedId={campaign?.platform ?? null}
              onSelect={(row) => setPlatform(row.platform)}
              emptyMessage={`Aún no hay propuestas de campaña en ${marketLabel(market)}.`}
            />
            <p className="text-[11px] text-muted-foreground">
              Distribución del presupuesto en %, Creators / Influencers, TikTok Ads y otros canales: pendientes, el
              backend solo modela Meta y Google.
            </p>
          </CardContent>
        </Card>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>No se pudo completar la operación</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {campaign ? (
        <CampaignPanels campaign={campaign} onValidate={validateWithCeo} />
      ) : (
        <Card>
          <CardContent>
            <EmptyState
              icon={Megaphone}
              title={`Sin propuesta de ${platformLabel(platform)} en ${marketLabel(market)}`}
              description="Fija el presupuesto y pulsa «Generar propuesta de campaña» para ver aquí audiencias, creatividad, rendimiento estimado y guardrails."
            />
          </CardContent>
        </Card>
      )}

      <NextStepBar
        steps={[
          { label: "Escaparate preparado", icon: ShoppingBag, state: storefront || listing ? "done" : "todo" },
          { label: "Propuesta de campaña", icon: Megaphone, state: campaign ? "done" : "current" },
          { label: "Validación de inversión", icon: Wallet, state: campaign ? "current" : "todo" },
          { label: "Simulación de operaciones", icon: Truck, state: "todo" },
          { label: "Lanzamiento", icon: Rocket, state: "todo" },
        ]}
        action={
          <Button type="button" disabled={!campaign} onClick={simulateOperations}>
            Simular operaciones
            <ArrowRight />
          </Button>
        }
      />
    </div>
  );
}
