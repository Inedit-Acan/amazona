"use client";

import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type PipelineRun } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const STEP_ORDER = [
  "research",
  "sourcing",
  "economics",
  "legal",
  "ecommerce",
  "marketplace",
  "marketing",
  "operations",
  "cfo",
] as const;

const STEP_LABELS: Record<string, string> = {
  research: "1. Research",
  sourcing: "2. Sourcing",
  economics: "3. Economics",
  legal: "4. Legal",
  ecommerce: "5. Ecommerce",
  marketplace: "6. Marketplace",
  marketing: "7. Marketing",
  operations: "8. Operations",
  cfo: "9. CFO",
};

const RUN_STATUS_STYLES: Record<string, string> = {
  COMPLETED: "text-emerald-600 dark:text-emerald-400",
  PARTIAL: "text-amber-600 dark:text-amber-400",
};

export default function PipelinePage() {
  const [category, setCategory] = useState("home");
  const [market, setMarket] = useState("us");
  const [destinationRegion, setDestinationRegion] = useState("mexico");
  const [salePrice, setSalePrice] = useState("50");
  const [dailyBudget, setDailyBudget] = useState("20");
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createPipelineRun({
        category,
        market,
        destination_region: destinationRegion,
        sale_price: Number(salePrice),
        daily_budget: Number(dailyBudget),
      });
      setRun(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Pipeline run failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pipeline"
        description="Run the full Fase 3 discovery chain (Research → Sourcing → Economics → Legal → Ecommerce → Marketplace → Marketing → Operations → CFO) as one continuous execution instead of clicking through each page and copying IDs by hand (Milestone 12, ADR 0005). The individual pages still exist for standalone use and debugging."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New pipeline run</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="category" className="text-sm font-medium">
                  Category
                </label>
                <input
                  id="category"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
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
                <label htmlFor="destinationRegion" className="text-sm font-medium">
                  Destination region
                </label>
                <input
                  id="destinationRegion"
                  value={destinationRegion}
                  onChange={(e) => setDestinationRegion(e.target.value)}
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
                  value={salePrice}
                  onChange={(e) => setSalePrice(e.target.value)}
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="dailyBudget" className="text-sm font-medium">
                  Daily budget
                </label>
                <input
                  id="dailyBudget"
                  type="number"
                  step="0.01"
                  value={dailyBudget}
                  onChange={(e) => setDailyBudget(e.target.value)}
                  required
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Pipeline run failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Running…" : "Run full pipeline"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {run ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Pipeline run</CardTitle>
            <span className={`text-sm font-semibold ${RUN_STATUS_STYLES[run.status] ?? ""}`}>{run.status}</span>
          </CardHeader>
          <CardContent className="space-y-4">
            {run.status === "PARTIAL" ? (
              <p className="text-sm text-muted-foreground">
                Stopped at step <strong>{run.failed_step}</strong> — no candidates to proceed with.
              </p>
            ) : null}

            <ul className="space-y-1 text-sm">
              {STEP_ORDER.filter((step) => run.steps[step]).map((step) => {
                const result = run.steps[step];
                return (
                  <li key={step} className="flex items-center justify-between">
                    <span>{STEP_LABELS[step]}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {result.recommendation ?? result.status ?? `${result.candidate_count ?? 0} candidates`}
                    </span>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
