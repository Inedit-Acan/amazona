"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type MarketplaceListing, type Storefront } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

interface ChannelProps {
  productId: string;
  setProductId: (value: string) => void;
  market: string;
  setMarket: (value: string) => void;
}

function OwnStoreChannel({ productId, setProductId, market, setMarket, onOptimizeMarketplace }: ChannelProps & {
  onOptimizeMarketplace: () => void;
}) {
  const [storefront, setStorefront] = useState<Storefront | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createStorefrontRun({ product_id: productId, market });
      setStorefront(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Storefront generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New storefront generation</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="ownStoreProductId" className="text-sm font-medium">
                  Product ID
                </label>
                <input
                  id="ownStoreProductId"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  placeholder="from a Research run"
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="ownStoreMarket" className="text-sm font-medium">
                  Market
                </label>
                <select
                  id="ownStoreMarket"
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="us">us</option>
                  <option value="eu">eu</option>
                  <option value="mx">mx</option>
                </select>
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Storefront generation failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Generating…" : "Generate storefront"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {storefront ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{storefront.store_slug}</CardTitle>
            <StatusChip status={storefront.launch_status} />
          </CardHeader>
          <CardContent className="space-y-4">
            {storefront.data?.landing_page_copy ? (
              <div className="rounded-md border p-3">
                <p className="font-medium">{storefront.data.landing_page_copy.headline}</p>
                <p className="text-sm text-muted-foreground">{storefront.data.landing_page_copy.subheadline}</p>
                <ul className="mt-2 list-inside list-disc text-sm">
                  {storefront.data.landing_page_copy.bullets.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
                <Button size="sm" className="mt-2" disabled>
                  {storefront.data.landing_page_copy.cta}
                </Button>
              </div>
            ) : null}

            {storefront.data?.catalog_entry ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Catalog entry</p>
                <p className="mt-1 text-sm">
                  SKU {storefront.data.catalog_entry.sku} · {storefront.data.catalog_entry.category} ·{" "}
                  {storefront.data.catalog_entry.price !== null
                    ? `$${storefront.data.catalog_entry.price.toFixed(2)}`
                    : "price TBD"}{" "}
                  · lead time {storefront.data.catalog_entry.lead_time_days ?? "unknown"}d
                </p>
              </div>
            ) : null}

            {storefront.data?.payment_gateway_plan ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  Payment gateway plan ({storefront.data.payment_gateway_plan.mode} mode —{" "}
                  {storefront.data.payment_gateway_plan.gateway})
                </p>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {storefront.data.payment_gateway_plan.checklist.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-muted-foreground">
                  Going live always requires explicit human approval — never automated.
                </p>
              </div>
            ) : null}

            {storefront.data?.conversion_tips && storefront.data.conversion_tips.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Conversion tips</p>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {storefront.data.conversion_tips.map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {storefront.data?.risks && storefront.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {storefront.data.risks.map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Button size="sm" variant="outline" onClick={onOptimizeMarketplace}>
              Optimize marketplace listing
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function AmazonChannel({ productId, setProductId, market, setMarket }: ChannelProps) {
  const router = useRouter();
  const [platform] = useState("amazon");
  const [listing, setListing] = useState<MarketplaceListing | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function planMarketingCampaign() {
    if (!listing) return;
    const params = new URLSearchParams({ product_id: listing.product_id, market: listing.market });
    router.push(`/marketing?${params.toString()}`);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createMarketplaceListingRun({ product_id: productId, market, platform });
      setListing(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Marketplace listing generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New marketplace listing</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5 sm:col-span-1">
                <label htmlFor="amazonProductId" className="text-sm font-medium">
                  Product ID
                </label>
                <input
                  id="amazonProductId"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  placeholder="from a Research run"
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="amazonMarket" className="text-sm font-medium">
                  Market
                </label>
                <select
                  id="amazonMarket"
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="us">us</option>
                  <option value="eu">eu</option>
                  <option value="mx">mx</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="amazonPlatform" className="text-sm font-medium">
                  Platform
                </label>
                <select id="amazonPlatform" value={platform} disabled className="w-full rounded-md border bg-background px-3 py-2 text-sm">
                  <option value="amazon">amazon</option>
                </select>
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Marketplace listing generation failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Generating…" : "Generate listing"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {listing ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{listing.platform} · {listing.market}</CardTitle>
            <StatusChip status={listing.listing_status} />
          </CardHeader>
          <CardContent className="space-y-4">
            {listing.data?.listing_content ? (
              <div className="rounded-md border p-3">
                <p className="font-medium">{listing.data.listing_content.title}</p>
                <ul className="mt-2 list-inside list-disc text-sm">
                  {listing.data.listing_content.bullet_points.map((bullet) => (
                    <li key={bullet}>{bullet}</li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-muted-foreground">
                  Backend keywords: {listing.data.listing_content.backend_keywords.join(", ")}
                </p>
              </div>
            ) : null}

            {listing.data?.competition_analysis ? (
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-xs font-medium text-muted-foreground">Competition analysis</p>
                  <DataProvenanceBadge status="estimated" tooltip={listing.data.competition_analysis.data_origin} />
                </div>
                <p className="mt-1 text-sm">
                  {listing.data.competition_analysis.competitor_count} competitors · avg price $
                  {listing.data.competition_analysis.avg_price.toFixed(2)} · avg rating{" "}
                  {listing.data.competition_analysis.avg_rating.toFixed(1)} · buy-box difficulty{" "}
                  {listing.data.competition_analysis.buy_box_difficulty}
                </p>
              </div>
            ) : null}

            {listing.data?.commission_breakdown ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Commission breakdown</p>
                <p className="mt-1 text-sm">
                  Referral fee {(listing.data.commission_breakdown.referral_fee_percent * 100).toFixed(0)}% +
                  fulfillment ${listing.data.commission_breakdown.fulfillment_fee_per_unit.toFixed(2)}/unit
                </p>
                <p
                  className={`text-sm font-medium ${
                    (listing.data.commission_breakdown.net_margin_per_unit ?? 0) < 0 ? "text-destructive" : ""
                  }`}
                >
                  Net margin per unit:{" "}
                  {listing.data.commission_breakdown.net_margin_per_unit !== null
                    ? `$${listing.data.commission_breakdown.net_margin_per_unit.toFixed(2)}`
                    : "unknown (no pricing data yet)"}
                </p>
              </div>
            ) : null}

            {listing.data?.inventory_policy ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Inventory policy</p>
                <p className="mt-1 text-sm">{listing.data.inventory_policy.fulfillment_method}</p>
              </div>
            ) : null}

            {listing.data?.risks && listing.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {listing.data.risks.map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Button size="sm" variant="outline" onClick={planMarketingCampaign}>
              Plan marketing campaign
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function EcommerceChannels() {
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialMarket = searchParams.get("market") ?? "us";

  const [channel, setChannel] = useState<"own-store" | "amazon">("own-store");
  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState(initialMarket);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tienda y canales de venta"
        description="Genera y gestiona la oferta comercial por canal — tienda propia y marketplaces — para un mismo producto, precio, proveedor y Legal Gate. Fase 3, Agentes 5-6. Sin tienda, dominio ni procesamiento de pagos reales todavía."
      />

      <Tabs value={channel} onValueChange={(value) => setChannel(value as "own-store" | "amazon")}>
        <TabsList>
          <TabsTrigger value="own-store">Tienda propia</TabsTrigger>
          <TabsTrigger value="amazon">Amazon</TabsTrigger>
        </TabsList>
        <TabsContent value="own-store">
          <OwnStoreChannel
            productId={productId}
            setProductId={setProductId}
            market={market}
            setMarket={setMarket}
            onOptimizeMarketplace={() => setChannel("amazon")}
          />
        </TabsContent>
        <TabsContent value="amazon">
          <AmazonChannel productId={productId} setProductId={setProductId} market={market} setMarket={setMarket} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function EcommercePage() {
  return (
    <Suspense fallback={null}>
      <EcommerceChannels />
    </Suspense>
  );
}
