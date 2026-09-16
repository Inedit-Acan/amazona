"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type EconomicAnalysis } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const RECOMMENDATION_STYLES: Record<string, string> = {
  GO: "text-emerald-600 dark:text-emerald-400",
  REVIEW: "text-amber-600 dark:text-amber-400",
  NO_GO: "text-destructive",
};

const SCENARIO_LABELS = {
  conservative: "Conservative",
  base: "Base",
  optimistic: "Optimistic",
} as const;

function EconomicsForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialSupplierQuoteId = searchParams.get("supplier_quote_id") ?? "";

  const [productId, setProductId] = useState(initialProductId);
  const [supplierQuoteId, setSupplierQuoteId] = useState(initialSupplierQuoteId);
  const [salePrice, setSalePrice] = useState(20.0);
  const [monthlyFixedCosts, setMonthlyFixedCosts] = useState(500.0);
  const [analysis, setAnalysis] = useState<EconomicAnalysis | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createEconomicAnalysisRun({
        product_id: productId,
        supplier_quote_id: supplierQuoteId,
        sale_price: salePrice,
        monthly_fixed_costs: monthlyFixedCosts,
      });
      setAnalysis(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Economic analysis run failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateThisAnalysis() {
    if (!analysis) return;
    const base = analysis.data?.scenarios?.base;
    const unitLandedCost = analysis.sale_price * (1 - analysis.margin_percent);
    const params = new URLSearchParams({
      title: `Validate economics for product ${analysis.product_id}`,
      unit_cost: String(unitLandedCost.toFixed(2)),
      sale_price: String(analysis.sale_price),
      monthly_fixed_costs: String(analysis.monthly_fixed_costs),
      monthly_unit_sales: String(Math.round(base?.monthly_unit_sales ?? 0)),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  function checkLegalCompliance() {
    if (!analysis) return;
    const params = new URLSearchParams({ product_id: analysis.product_id });
    router.push(`/legal?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Economics"
        description="Landed cost, margin, and conservative/base/optimistic scenarios for a researched product + sourced supplier — Fase 3, Agente 3. Demand-to-sales conversion and scenario factors are simulated placeholders."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New economic analysis</CardTitle>
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
                <label htmlFor="supplierQuoteId" className="text-sm font-medium">
                  Supplier quote ID
                </label>
                <input
                  id="supplierQuoteId"
                  value={supplierQuoteId}
                  onChange={(e) => setSupplierQuoteId(e.target.value)}
                  placeholder="from a Sourcing run"
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="salePrice" className="text-sm font-medium">
                  Sale price
                </label>
                <input
                  id="salePrice"
                  type="number"
                  step="0.01"
                  min={0}
                  value={salePrice}
                  onChange={(e) => setSalePrice(Number(e.target.value))}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="monthlyFixedCosts" className="text-sm font-medium">
                  Monthly fixed costs
                </label>
                <input
                  id="monthlyFixedCosts"
                  type="number"
                  step="0.01"
                  min={0}
                  value={monthlyFixedCosts}
                  onChange={(e) => setMonthlyFixedCosts(Number(e.target.value))}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Economic analysis failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId || !supplierQuoteId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Analyzing…" : "Run analysis"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {analysis ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Viability report</CardTitle>
            <span className={`text-sm font-semibold ${RECOMMENDATION_STYLES[analysis.recommendation] ?? ""}`}>
              {analysis.recommendation}
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Base margin {(analysis.margin_percent * 100).toFixed(1)}% · confidence{" "}
              {(analysis.confidence * 100).toFixed(0)}%
            </p>

            <div className="grid gap-3 sm:grid-cols-3">
              {(Object.keys(SCENARIO_LABELS) as (keyof typeof SCENARIO_LABELS)[]).map((key) => {
                const scenario = analysis.data?.scenarios?.[key];
                if (!scenario) return null;
                return (
                  <div key={key} className="rounded-md border p-3">
                    <p className="text-xs font-medium text-muted-foreground">{SCENARIO_LABELS[key]}</p>
                    <p className="mt-1 text-sm">{Math.round(scenario.monthly_unit_sales)} units/mo</p>
                    <p className="text-sm">Revenue {scenario.monthly_revenue.toFixed(2)}</p>
                    <p
                      className={`text-sm font-medium ${scenario.monthly_profit < 0 ? "text-destructive" : ""}`}
                    >
                      Profit {scenario.monthly_profit.toFixed(2)}
                    </p>
                  </div>
                );
              })}
            </div>

            {analysis.data?.risks && analysis.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {analysis.data.risks.map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={checkLegalCompliance}>
                Check legal compliance
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

export default function EconomicsPage() {
  return (
    <Suspense fallback={null}>
      <EconomicsForm />
    </Suspense>
  );
}
