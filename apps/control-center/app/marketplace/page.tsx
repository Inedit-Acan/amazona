"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type MarketplaceListing } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const LISTING_STATUS_STYLES: Record<string, string> = {
  READY: "text-emerald-600 dark:text-emerald-400",
  NEEDS_REVIEW: "text-amber-600 dark:text-amber-400",
  BLOCKED: "text-destructive",
};

function MarketplaceForm() {
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialMarket = searchParams.get("market") ?? "us";

  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState(initialMarket);
  const [platform, setPlatform] = useState("amazon");
  const [listing, setListing] = useState<MarketplaceListing | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      <PageHeader
        title="Marketplace"
        description="Create/optimize a marketplace listing, simulated competition analysis, real commission/net-margin math, and an inventory policy (no real stock) — Fase 3, Agente 6. Competition data is simulated, never real Amazon SP-API data (see README's SP-API policy)."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New marketplace listing</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5 sm:col-span-1">
                <label htmlFor="productId" className="text-sm font-medium">
                  Product ID
                </label>
                <input
                  id="productId"
                  value={productId}
                  onChange={(e) => setProductId(e.target.value)}
                  placeholder="from a Research run"
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="market" className="text-sm font-medium">
                  Market
                </label>
                <select
                  id="market"
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
                <label htmlFor="platform" className="text-sm font-medium">
                  Platform
                </label>
                <select
                  id="platform"
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
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
            <span className={`text-sm font-semibold ${LISTING_STATUS_STYLES[listing.listing_status] ?? ""}`}>
              {listing.listing_status}
            </span>
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
                <p className="text-xs font-medium text-muted-foreground">
                  Competition analysis (source: {listing.data.competition_analysis.data_origin})
                </p>
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
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function MarketplacePage() {
  return (
    <Suspense fallback={null}>
      <MarketplaceForm />
    </Suspense>
  );
}
