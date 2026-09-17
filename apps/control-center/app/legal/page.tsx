"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type LegalAnalysis } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { RiskList } from "@/components/risk-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

function LegalForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";

  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState("eu");
  const [certificationAvailable, setCertificationAvailable] = useState(false);
  const [analysis, setAnalysis] = useState<LegalAnalysis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createLegalAnalysisRun({
        product_id: productId,
        market,
        certification_available: certificationAvailable,
      });
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Legal analysis run failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateThisAnalysis() {
    if (!analysis) return;
    const requiresCertification = (analysis.data?.required_certifications?.length ?? 0) > 0;
    const params = new URLSearchParams({
      title: `Validate legal compliance for product ${analysis.product_id} in ${analysis.market}`,
      restricted_category: String(analysis.restricted ?? false),
      requires_certification: String(requiresCertification),
      certification_available: String(certificationAvailable),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function generateStorefront() {
    if (!analysis) return;
    const params = new URLSearchParams({ product_id: analysis.product_id });
    router.push(`/ecommerce?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Legal"
        description="Regulatory requirements, certifications, legal risks, recent regulatory changes, and a T&C draft per product + market — Fase 3, Agente 4. Simulated regulatory dataset, not real legal research or advice."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New legal compliance analysis</CardTitle>
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
              <div className="flex items-center gap-2 sm:col-span-2">
                <input
                  id="certificationAvailable"
                  type="checkbox"
                  checked={certificationAvailable}
                  onChange={(e) => setCertificationAvailable(e.target.checked)}
                  className="size-4"
                />
                <label htmlFor="certificationAvailable" className="text-sm font-medium">
                  Required certifications already held
                </label>
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Legal analysis failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Analyzing…" : "Run analysis"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {analysis ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Compliance report</CardTitle>
            <StatusChip status={analysis.recommendation} />
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {analysis.restricted ? "Restricted category" : "Not a restricted category"} in{" "}
              {analysis.market} · confidence {(analysis.confidence * 100).toFixed(0)}%
            </p>

            <div>
              <p className="text-xs font-medium text-muted-foreground">Required certifications</p>
              <p className="mt-1 text-sm">
                {analysis.data?.required_certifications?.length
                  ? analysis.data.required_certifications.join(", ")
                  : "None"}
              </p>
            </div>

            {analysis.data?.recent_changes && analysis.data.recent_changes.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Recent regulatory changes</p>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {analysis.data.recent_changes.map((change) => (
                    <li key={change.date}>
                      {change.date}: {change.description}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <RiskList risks={analysis.data?.risks ?? []} />

            {analysis.data?.terms_and_conditions ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Terms &amp; conditions draft</p>
                <pre className="mt-1 whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-xs">
                  {analysis.data.terms_and_conditions}
                </pre>
              </div>
            ) : null}

            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={generateStorefront}>
                Generate storefront
              </Button>
              <Button size="sm" variant="outline" onClick={validateThisAnalysis}>
                Validate this analysis
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function LegalPage() {
  return (
    <Suspense fallback={null}>
      <LegalForm />
    </Suspense>
  );
}
