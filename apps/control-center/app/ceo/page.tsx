"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ChevronDown, Loader2 } from "lucide-react";
import { api, ApiError, type AgentExecution, type Agent, type Decision, type RunResult } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

const AgentGraph3D = dynamic(
  () => import("@/components/graph3d/agent-graph-3d").then((mod) => mod.AgentGraph3D),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full rounded-xl" /> },
);

const DEFAULT_CONTEXT = {
  product_validation: { estimated_monthly_searches: 12000, competition_level: "low" },
  supplier_sourcing: { unit_cost: 5.0, lead_time_days: 20, supplier_verified: true },
  finance_validation: { unit_cost: 5.0, sale_price: 20.0, monthly_unit_sales: 300, monthly_fixed_costs: 500.0 },
  legal_validation: { restricted_category: false, requires_certification: false, certification_available: true },
  requests_simulated_spend: true,
  spend_action: "launch_marketing_campaign",
  spend_amount: 150.0,
};

/** Builds the initial form state from a Research page handoff
 * (?title=&product_name=&category=&demand_signal=&competition_level=), a
 * Sourcing page handoff (?title=&unit_cost=&lead_time_days=&supplier_verified=),
 * an Economics page handoff (?title=&unit_cost=&sale_price=&monthly_fixed_costs=&monthly_unit_sales=),
 * a Legal page handoff (?title=&restricted_category=&requires_certification=&certification_available=),
 * a Marketing page handoff (?title=&spend_amount=),
 * or the default example context when none of that is present.
 *
 * The Legal handoff is what replaces legal_validation.restricted_category —
 * a value typed by hand since Milestone 1 — with the Legal Compliance
 * agent's real analysis of the product's category and target market. The
 * Marketing handoff similarly replaces spend_amount=150.0 — an example
 * value hardcoded since Milestone 1, when spend_action was already
 * "launch_marketing_campaign" but no marketing agent existed yet to
 * recommend a real number — with the Marketing Campaign agent's real
 * recommended daily budget. */
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
  const restrictedCategory = params.get("restricted_category");
  const requiresCertification = params.get("requires_certification");
  const certificationAvailable = params.get("certification_available");
  const spendAmount = params.get("spend_amount");

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
      legal_validation: {
        restricted_category: restrictedCategory
          ? restrictedCategory === "true"
          : DEFAULT_CONTEXT.legal_validation.restricted_category,
        requires_certification: requiresCertification
          ? requiresCertification === "true"
          : DEFAULT_CONTEXT.legal_validation.requires_certification,
        certification_available: certificationAvailable
          ? certificationAvailable === "true"
          : DEFAULT_CONTEXT.legal_validation.certification_available,
      },
      spend_amount: spendAmount ? Number(spendAmount) : DEFAULT_CONTEXT.spend_amount,
    },
  };
}

const DECISION_STATUS_LABEL: Record<string, string> = {
  GO: "Aprobado (GO)",
  NO_GO: "Rechazado (NO_GO)",
  REVIEW: "Requiere revisión",
  HUMAN_APPROVAL: "Esperando aprobación humana",
};

function CeoForm() {
  const searchParams = useSearchParams();
  const initial = buildInitialState(searchParams);

  const [title, setTitle] = useState(initial.title);
  const [createdBy, setCreatedBy] = useState("owner@amazona.local");
  const [context, setContext] = useState(JSON.stringify(initial.context, null, 2));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [executions, setExecutions] = useState<AgentExecution[]>([]);
  const [agentsById, setAgentsById] = useState<Map<string, Agent>>(new Map());

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
    setRunResult(null);
    setDecision(null);
    setExecutions([]);
    try {
      const objective = await api.createObjective({ title, created_by: createdBy, context: parsedContext });
      const result = await api.runObjective(objective.id);
      setRunResult(result);

      // Best-effort enrichment — the graph and execution feed still work
      // from `result` alone (status only) if either of these fails.
      const [fullDecision, agentExecutions, agents] = await Promise.all([
        api.getDecision(result.id).catch(() => null),
        api.listAgentExecutions().catch(() => []),
        api.listAgents().catch(() => []),
      ]);
      setDecision(fullDecision);
      setExecutions(agentExecutions.filter((e) => e.correlation_id === result.correlation_id));
      setAgentsById(new Map(agents.map((a) => [a.id, a])));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to run objective.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Director ejecutivo"
        description="Centro de orquestación multiagente: un objetivo entra por CEO, se reparte entre los agentes especializados y el Decision Engine sintetiza la decisión. Simulado — sin dinero, pedidos ni proveedores reales."
      />

      <Card>
        <CardHeader>
          <CardTitle>Grafo de agentes</CardTitle>
        </CardHeader>
        <CardContent>
          <AgentGraph3D decision={decision} />
        </CardContent>
      </Card>

      {runResult ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Resumen de misión</CardTitle>
            <StatusChip status={runResult.status} />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
              <div>
                <p className="text-xs text-muted-foreground">Resultado</p>
                <p className="font-medium">{DECISION_STATUS_LABEL[runResult.status] ?? runResult.status}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Confianza</p>
                <p className="font-medium">
                  {runResult.confidence != null ? runResult.confidence.toFixed(2) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Score de oportunidad</p>
                <p className="font-medium">
                  {runResult.opportunity_score != null ? runResult.opportunity_score.toFixed(2) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Agentes ejecutados</p>
                <p className="font-medium">{executions.length}</p>
              </div>
            </div>

            {runResult.rationale ? <p className="text-sm text-muted-foreground">{runResult.rationale}</p> : null}

            {executions.length > 0 ? (
              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground">Vista previa de ejecución</p>
                <ul className="divide-y rounded-md border">
                  {executions.map((execution) => (
                    <li key={execution.id} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {agentsById.get(execution.agent_id)?.name ?? execution.agent_id}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {execution.capability.replace(/_/g, " ")} · {execution.duration_ms}ms
                        </p>
                      </div>
                      <StatusChip status={execution.success ? "COMPLETED" : "FAILED"} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Button
              size="sm"
              variant="outline"
              nativeButton={false}
              render={<Link href={`/projects/${runResult.project_id}`} />}
            >
              Ver proyecto
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Nuevo objetivo</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <label htmlFor="title" className="text-sm font-medium">
                Objetivo
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
                Solicitado por
              </label>
              <input
                id="createdBy"
                value={createdBy}
                onChange={(e) => setCreatedBy(e.target.value)}
                required
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground"
              >
                <ChevronDown className={`size-4 transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
                Contexto avanzado
              </button>
              {showAdvanced ? (
                <div className="mt-2 space-y-1.5">
                  <label htmlFor="context" className="text-sm font-medium">
                    Contexto simulado (valores fijos para cada agente)
                  </label>
                  <textarea
                    id="context"
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    rows={14}
                    className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    Sin dinero, pedidos, proveedores ni presentaciones fiscales reales — valores de simulación.
                  </p>
                </div>
              ) : null}
            </div>

            {error ? (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>No se pudo ejecutar este objetivo</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
              {submitting ? "Ejecutando…" : "Crear y ejecutar objetivo"}
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
