"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type MarketingCampaign } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const CAMPAIGN_STATUS_STYLES: Record<string, string> = {
  READY: "text-emerald-600 dark:text-emerald-400",
  NEEDS_REVIEW: "text-amber-600 dark:text-amber-400",
  BLOCKED: "text-destructive",
};

function MarketingForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialMarket = searchParams.get("market") ?? "us";

  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState(initialMarket);
  const [platform, setPlatform] = useState("meta");
  const [dailyBudget, setDailyBudget] = useState(20.0);
  const [campaign, setCampaign] = useState<MarketingCampaign | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createMarketingCampaignRun({
        product_id: productId,
        market,
        platform,
        daily_budget: dailyBudget,
      });
      setCampaign(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Marketing campaign generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function validateThisCampaign() {
    if (!campaign) return;
    const params = new URLSearchParams({
      title: `Validate ${campaign.platform} campaign for product ${campaign.product_id}`,
      spend_amount: String(campaign.daily_budget),
    });
    router.push(`/ceo?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Marketing"
        description="Design a campaign proposal — audience segments, ad creative (text + image brief), simulated performance estimate, and a budget recommendation — from real product/pricing/legal/listing data. Fase 3, Agente 7. No real ad spend or Meta/Google/TikTok Ads credentials."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New campaign proposal</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 sm:grid-cols-4">
              <div className="space-y-1.5 sm:col-span-2">
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
                  <option value="meta">meta</option>
                  <option value="google">google</option>
                </select>
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <label htmlFor="dailyBudget" className="text-sm font-medium">
                  Daily budget (simulated)
                </label>
                <input
                  id="dailyBudget"
                  type="number"
                  step="0.01"
                  min={0}
                  value={dailyBudget}
                  onChange={(e) => setDailyBudget(Number(e.target.value))}
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                />
              </div>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Marketing campaign generation failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Generating…" : "Generate campaign proposal"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {campaign ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>
              {campaign.platform} · {campaign.market} · ${campaign.daily_budget.toFixed(2)}/day
            </CardTitle>
            <span className={`text-sm font-semibold ${CAMPAIGN_STATUS_STYLES[campaign.campaign_status] ?? ""}`}>
              {campaign.campaign_status}
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            {campaign.data?.ad_creative ? (
              <div className="rounded-md border p-3">
                <p className="font-medium">{campaign.data.ad_creative.headline}</p>
                <p className="mt-1 text-sm text-muted-foreground">{campaign.data.ad_creative.primary_text}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Image brief: {campaign.data.ad_creative.image_brief}
                </p>
                <Button size="sm" className="mt-2" disabled>
                  {campaign.data.ad_creative.cta}
                </Button>
              </div>
            ) : null}

            {campaign.data?.audience_segments && campaign.data.audience_segments.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Audience segments</p>
                <ul className="mt-1 space-y-1 text-sm">
                  {campaign.data.audience_segments.map((segment) => (
                    <li key={segment.name}>
                      {segment.name} ({segment.age_range}) — reach ~{segment.estimated_reach.toLocaleString()}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {campaign.data?.performance_estimate ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  Performance estimate (source: {campaign.data.performance_estimate.data_origin})
                </p>
                <p className="mt-1 text-sm">
                  CPC ${campaign.data.performance_estimate.avg_cpc.toFixed(2)} · CTR{" "}
                  {(campaign.data.performance_estimate.avg_ctr * 100).toFixed(1)}% · conversion{" "}
                  {(campaign.data.performance_estimate.conversion_rate * 100).toFixed(1)}%
                </p>
                <p
                  className={`text-sm font-medium ${
                    (campaign.data.performance_estimate.projected_roas ?? 1) < 1
                      ? "text-destructive"
                      : ""
                  }`}
                >
                  Projected ROAS:{" "}
                  {campaign.data.performance_estimate.projected_roas !== null
                    ? `${campaign.data.performance_estimate.projected_roas.toFixed(2)}x`
                    : "unknown (no pricing data yet)"}
                </p>
              </div>
            ) : null}

            {campaign.data?.budget_recommendation ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Budget recommendation</p>
                <p className="mt-1 text-sm">{campaign.data.budget_recommendation}</p>
              </div>
            ) : null}

            {campaign.data?.risks && campaign.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {campaign.data.risks.map((risk) => (
                    <li key={risk}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Button size="sm" variant="outline" onClick={validateThisCampaign}>
              Validate this campaign
            </Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function MarketingPage() {
  return (
    <Suspense fallback={null}>
      <MarketingForm />
    </Suspense>
  );
}
