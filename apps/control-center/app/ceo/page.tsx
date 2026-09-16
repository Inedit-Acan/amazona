"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle, Loader2 } from "lucide-react";

const DEFAULT_CONTEXT = {
  product_validation: { estimated_monthly_searches: 12000, competition_level: "low" },
  supplier_sourcing: { unit_cost: 5.0, lead_time_days: 20, supplier_verified: true },
  finance_validation: { unit_cost: 5.0, sale_price: 20.0, monthly_unit_sales: 300, monthly_fixed_costs: 500.0 },
  legal_validation: { restricted_category: false },
  requests_simulated_spend: true,
  spend_action: "launch_marketing_campaign",
  spend_amount: 150.0,
};

/** Builds the initial form state from a Research page handoff
 * (?title=&product_name=&category=&demand_signal=&competition_level=), a
 * Sourcing page handoff (?title=&unit_cost=&lead_time_days=&supplier_verified=),
 * an Economics page handoff (?title=&unit_cost=&sale_price=&monthly_fixed_costs=&monthly_unit_sales=),
 * or the default example context when none of that is present. */
function buildInitialState(params: URLSearchParams) {
  const title = params.get("title");
  const demandSignal = params.get("demand_signal");
  const competitionLevel = params.get("competition_level");
  const unitCost = params.get("unit_cost");
  const leadTimeDays = params.get("lead_time_days");
  const supplierVerified = params.get("supplier_verified");
  const salePrice = params.get("sale_price");
  const monthlyFixedCosts = params.get("monthly_fixed_costs");
  const monthlyUnitSales = params.get("monthly_unit_sales");

  if (!title) {
    return { title: "Validate wireless earbuds opportunity", context: DEFAULT_CONTEXT };
  }

  const estimatedMonthlySearches = demandSignal ? Math.round(Number(demandSignal) * 15000) : 12000;
  return {
    title,
    context: {
      ...DEFAULT_CONTEXT,
      product_validation: {
        estimated_monthly_searches: estimatedMonthlySearches,
        competition_level: competitionLevel || "medium",
      },
      supplier_sourcing: {
        unit_cost: unitCost ? Number(unitCost) : DEFAULT_CONTEXT.supplier_sourcing.unit_cost,
        lead_time_days: leadTimeDays
          ? Number(leadTimeDays)
          : DEFAULT_CONTEXT.supplier_sourcing.lead_time_days,
        supplier_verified: supplierVerified
          ? supplierVerified === "true"
          : DEFAULT_CONTEXT.supplier_sourcing.supplier_verified,
      },
      finance_validation: {
        unit_cost: unitCost ? Number(unitCost) : DEFAULT_CONTEXT.finance_validation.unit_cost,
        sale_price: salePrice ? Number(salePrice) : DEFAULT_CONTEXT.finance_validation.sale_price,
        monthly_unit_sales: monthlyUnitSales
          ? Number(monthlyUnitSales)
          : DEFAULT_CONTEXT.finance_validation.monthly_unit_sales,
        monthly_fixed_costs: monthlyFixedCosts
          ? Number(monthlyFixedCosts)
          : DEFAULT_CONTEXT.finance_validation.monthly_fixed_costs,
      },
    },
  };
}

function CeoForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initial = buildInitialState(searchParams);

  const [title, setTitle] = useState(initial.title);
  const [createdBy, setCreatedBy] = useState("owner@amazona.local");
  const [context, setContext] = useState(JSON.stringify(initial.context, null, 2));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    let parsedContext: unknown;
    try {
      parsedContext = JSON.parse(context);
    } catch {
      setError("Context must be valid JSON.");
      return;
    }

    setSubmitting(true);
    try {
      const objective = await api.createObjective({ title, created_by: createdBy, context: parsedContext });
      const decision = await api.runObjective(objective.id);
      router.push(`/projects/${decision.project_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to run objective.");
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="CEO"
        description="Submit a simulated product-validation objective. The CEO plans the task graph, routes it to specialist agents, and returns a deterministic decision."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New objective</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <label htmlFor="title" className="text-sm font-medium">
                Title
              </label>
              <input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="createdBy" className="text-sm font-medium">
                Requested by
              </label>
              <input
                id="createdBy"
                value={createdBy}
                onChange={(e) => setCreatedBy(e.target.value)}
                required
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="context" className="text-sm font-medium">
                Simulated context (fixture inputs for each agent)
              </label>
              <textarea
                id="context"
                value={context}
                onChange={(e) => setContext(e.target.value)}
                rows={14}
                className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                No real money, orders, suppliers, or tax submissions — these are simulated fixture values only.
              </p>
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>Could not run this objective</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Running…" : "Create & run objective"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function CeoPage() {
  return (
    <Suspense fallback={null}>
      <CeoForm />
    </Suspense>
  );
}
