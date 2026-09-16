"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError, api, type OperationsRecord } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const OPERATIONS_STATUS_STYLES: Record<string, string> = {
  READY: "text-emerald-600 dark:text-emerald-400",
  NEEDS_REVIEW: "text-amber-600 dark:text-amber-400",
  BLOCKED: "text-destructive",
};

function OperationsForm() {
  const searchParams = useSearchParams();
  const initialProductId = searchParams.get("product_id") ?? "";
  const initialMarket = searchParams.get("market") ?? "us";

  const [productId, setProductId] = useState(initialProductId);
  const [market, setMarket] = useState(initialMarket);
  const [record, setRecord] = useState<OperationsRecord | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await api.createOperationsRun({ product_id: productId, market });
      setRecord(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Operations report generation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Operations"
        description="Simulate one sample order (with tracking), supplier coordination, a returns policy, and a support-ticket triage (AI vs human) — from real product/sourcing/pricing/legal data. Fase 3, Agente 8 — the last of the 8 operational agents. No real orders, customers, CRM, or ticketing integration."
      />

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>New operations report</CardTitle>
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
                <AlertTitle>Operations report generation failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting || !productId}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Generating…" : "Generate operations report"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {record ? (
        <Card className="max-w-3xl">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{record.market}</CardTitle>
            <span className={`text-sm font-semibold ${OPERATIONS_STATUS_STYLES[record.operations_status] ?? ""}`}>
              {record.operations_status}
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            {record.data?.order ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  Sample order {record.data.order.order_id} (qty {record.data.order.quantity})
                </p>
                <ul className="mt-1 space-y-0.5 text-sm">
                  {record.data.order.tracking.stages.map((stage) => (
                    <li key={stage.stage}>
                      Day {stage.day_offset}: {stage.stage.replace(/_/g, " ")}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {record.data?.supplier_coordination ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Supplier coordination</p>
                <p className="mt-1 text-sm">
                  Lead time {record.data.supplier_coordination.lead_time_days ?? "unknown"}d ·{" "}
                  {record.data.supplier_coordination.supplier_verified ? "verified" : "not verified"} supplier
                </p>
              </div>
            ) : null}

            {record.data?.return_policy ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Return policy</p>
                <p className="mt-1 text-sm">
                  {record.data.return_policy.eligibility_window_days}-day window ·{" "}
                  {(record.data.return_policy.restocking_fee_percent * 100).toFixed(0)}% restocking fee ·{" "}
                  refund estimate{" "}
                  {record.data.return_policy.refund_estimate !== null
                    ? `$${record.data.return_policy.refund_estimate.toFixed(2)}`
                    : "unknown (no pricing data yet)"}
                </p>
              </div>
            ) : null}

            {record.data?.support_ticket_example ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Support ticket example</p>
                <p className="mt-1 text-sm">
                  {record.data.support_ticket_example.ticket_type.replace(/_/g, " ")} —{" "}
                  {record.data.support_ticket_example.ai_resolvable
                    ? "resolved by AI"
                    : `escalated to a human (${record.data.support_ticket_example.escalation_reason})`}
                </p>
              </div>
            ) : null}

            {record.data?.risks && record.data.risks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-muted-foreground">Risks</p>
                <ul className="mt-1 list-inside list-disc text-sm text-destructive">
                  {record.data.risks.map((risk) => (
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

export default function OperationsPage() {
  return (
    <Suspense fallback={null}>
      <OperationsForm />
    </Suspense>
  );
}
