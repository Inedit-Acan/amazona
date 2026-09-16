"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type SupplierQuote } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

function SourcingForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialCategory = searchParams.get("category") ?? "electronics";

  const [productId, setProductId] = useState(initialProductId);
  const [category, setCategory] = useState(initialCategory);
  const [destinationRegion, setDestinationRegion] = useState("mexico");
  const [maxResults, setMaxResults] = useState(5);
  const [quotes, setQuotes] = useState<SupplierQuote[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const run = await api.createSourcingRun({
        product_id: productId,
        category,
        destination_region: destinationRegion,
        max_results: maxResults,
      });
      setQuotes(run.quotes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sourcing run failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateWithSupplier(quote: SupplierQuote) {
    const supplierName = quote.data?.name ?? "supplier";
    const params = new URLSearchParams({
      title: `Validate sourcing ${supplierName} for product ${productId}`,
      unit_cost: String(quote.unit_price),
      lead_time_days: String(quote.lead_time_days),
      supplier_verified: String(quote.verified),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function analyzeEconomics(quote: SupplierQuote) {
    const params = new URLSearchParams({
      product_id: productId,
      supplier_quote_id: quote.id,
    });
    router.push(`/economics?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sourcing"
        description="Discover and rank candidate suppliers for a product by simulated total landed cost — Fase 3, Agente 2. Fixture-driven supplier/logistics data, no live sources yet."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New sourcing run</CardTitle>
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
                <label htmlFor="category" className="text-sm font-medium">
                  Category
                </label>
                <select
                  id="category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="electronics">electronics</option>
                  <option value="home">home</option>
                  <option value="accessories">accessories</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="destinationRegion" className="text-sm font-medium">
                  Destination region
                </label>
                <select
                  id="destinationRegion"
                  value={destinationRegion}
                  onChange={(e) => setDestinationRegion(e.target.value)}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="mexico">mexico</option>
                  <option value="eu">eu</option>
                  <option value="china">china</option>
                  <option value="vietnam">vietnam</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="maxResults" className="text-sm font-medium">
                  Max results
                </label>
                <input
                  id="maxResults"
                  type="number"
                  min={1}
                  max={20}
                  value={maxResults}
                  onChange={(e) => setMaxResults(Number(e.target.value))}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Sourcing run failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Sourcing…" : "Run sourcing"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {quotes ? (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            {quotes.length === 0
              ? "No suppliers found for this category."
              : `${quotes.length} supplier${quotes.length === 1 ? "" : "s"}, ranked by total landed cost`}
          </h2>
          {quotes.map((quote) => (
            <Card key={quote.id}>
              <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium">
                    {quote.data?.name ?? quote.supplier_id}
                    {!quote.verified ? (
                      <span className="ml-2 text-xs font-normal text-destructive">unverified</span>
                    ) : null}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {quote.data?.region} · MOQ {quote.moq} · lead time {quote.lead_time_days}d · reliability{" "}
                    {quote.reliability_score.toFixed(2)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Unit price {quote.unit_price.toFixed(2)} + logistics {quote.logistics_cost_per_unit.toFixed(2)}{" "}
                    = total landed {quote.total_landed_cost_per_unit.toFixed(2)}/unit
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => analyzeEconomics(quote)}>
                    Analyze economics
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => validateWithSupplier(quote)}>
                    Validate with this supplier
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function SourcingPage() {
  return (
    <Suspense fallback={null}>
      <SourcingForm />
    </Suspense>
  );
}
