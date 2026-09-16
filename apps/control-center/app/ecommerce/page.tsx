"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type Storefront } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const LAUNCH_STATUS_STYLES: Record<string, string> = {
  READY: "text-emerald-600 dark:text-emerald-400",
  NEEDS_REVIEW: "text-amber-600 dark:text-amber-400",
  BLOCKED: "text-destructive",
};

function EcommerceForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";

  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState("us");
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

  function optimizeMarketplaceListing() {
    if (!storefront) return;
    const params = new URLSearchParams({ product_id: storefront.product_id, market: storefront.market });
    router.push(`/marketplace?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ecommerce"
        description="Generate a storefront draft — landing page copy, a simulated payment gateway plan, a catalog entry, and conversion tips — from real product, sourcing, economics, and legal data. Fase 3, Agente 5. No real store, domain, or payment processing yet."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New storefront generation</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
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
            <span
              className={`text-sm font-semibold ${LAUNCH_STATUS_STYLES[storefront.launch_status] ?? ""}`}
            >
              {storefront.launch_status}
            </span>
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

            <Button size="sm" variant="outline" onClick={optimizeMarketplaceListing}>
              Optimize marketplace listing
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function EcommercePage() {
  return (
    <Suspense fallback={null}>
      <EcommerceForm />
    </Suspense>
  );
}
