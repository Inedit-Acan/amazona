"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle, Loader2 } from "lucide-react";

const EXAMPLE_CONTEXT = {
  product_validation: { estimated_monthly_searches: 12000, competition_level: "low" },
  supplier_sourcing: { unit_cost: 5.0, lead_time_days: 20, supplier_verified: true },
  finance_validation: { unit_cost: 5.0, sale_price: 20.0, monthly_unit_sales: 300, monthly_fixed_costs: 500.0 },
  legal_validation: { restricted_category: false },
  requests_simulated_spend: true,
  spend_action: "launch_marketing_campaign",
  spend_amount: 150.0,
};

export default function CeoPage() {
  const router = useRouter();
  const [title, setTitle] = useState("Validate wireless earbuds opportunity");
  const [createdBy, setCreatedBy] = useState("owner@amazona.local");
  const [context, setContext] = useState(JSON.stringify(EXAMPLE_CONTEXT, null, 2));
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
