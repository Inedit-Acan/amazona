"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type CFOReport } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const HEALTH_STATUS_STYLES: Record<string, string> = {
  HEALTHY: "text-emerald-600 dark:text-emerald-400",
  AT_RISK: "text-amber-600 dark:text-amber-400",
  CRITICAL: "text-destructive",
  NEEDS_REVIEW: "text-amber-600 dark:text-amber-400",
};

function formatPercent(value: number | null): string {
  return value === null ? "n/a" : `${(value * 100).toFixed(0)}%`;
}

export default function CFOPage() {
  const [report, setReport] = useState<CFOReport | null>(null);
  const [recentReports, setRecentReports] = useState<CFOReport[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listCFORuns()
      .then(setRecentReports)
      .catch(() => undefined);
  }, []);

  async function handleGenerate() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createCFORun();
      setReport(result);
      setRecentReports(await api.listCFORuns());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "CFO report generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="CFO"
        description="Consolidate EconomicAnalysis (Agente 3) + MarketingCampaign (Agente 7) + BudgetEngine reservations into one aggregate financial-health report across the whole catalog — not per product. Aggregate reporting only: this agent never emits invoices; real billing must go through a certified Verifactu-compliant third-party system."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New financial health report</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error ? (
            <Alert variant="destructive">
              <AlertTriangle className="size-4" />
              <AlertTitle>CFO report generation failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <Button onClick={handleGenerate} disabled={submitting}>
            {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
            {submitting ? "Generating…" : "Generate financial health report"}
          </Button>
        </CardContent>
      </Card>

      {report ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Financial health</CardTitle>
            <span
              className={`text-sm font-semibold ${HEALTH_STATUS_STYLES[report.financial_health_status] ?? ""}`}
            >
              {report.financial_health_status}
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">
              Recommendation <strong>{report.recommendation}</strong> · confidence{" "}
              {(report.confidence * 100).toFixed(0)}%
            </p>

            {report.data ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Products analyzed</p>
                  <p className="mt-1 text-sm">
                    {report.data.total_products_analyzed} total — {report.data.go_count} GO,{" "}
                    {report.data.review_count} REVIEW, {report.data.no_go_count} NO_GO (
                    {formatPercent(report.data.no_go_ratio)} NO_GO)
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Campaigns</p>
                  <p className="mt-1 text-sm">
                    {report.data.active_campaigns}/{report.data.total_campaigns} active · $
                    {report.data.total_daily_budget.toFixed(2)} total daily budget
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Budget utilization</p>
                  <p className="mt-1 text-sm">
                    {formatPercent(report.data.budget_utilization)} of ${" "}
                    {report.data.total_budget_hard_limit.toFixed(2)} hard limit (reserved $
                    {report.data.total_reserved.toFixed(2)}, committed $
                    {report.data.total_committed.toFixed(2)}, spent $
                    {report.data.total_spent.toFixed(2)})
                  </p>
                </div>
              </div>
            ) : null}

            {report.data?.risks && report.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {report.data.risks.map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {recentReports.length > 0 ? (
        <Card className="max-w-3xl">
          <CardHeader>
            <CardTitle>Recent reports</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm">
              {recentReports.map((r) => (
                <li key={r.correlation_id} className="flex items-center justify-between">
                  <span className="font-mono text-xs text-muted-foreground">{r.correlation_id}</span>
                  <span className={HEALTH_STATUS_STYLES[r.financial_health_status] ?? ""}>
                    {r.financial_health_status}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
