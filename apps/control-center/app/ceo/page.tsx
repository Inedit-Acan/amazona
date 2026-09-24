"use client";

import Link from "next/link";
import { NeuralNexusGraph } from "@/components/neural-nexus/neural-nexus-graph";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertTriangle, ChevronDown, Loader2, Plus, Save, X } from "lucide-react";
import { api, ApiError, type AgentExecution, type Agent, type Decision, type RunResult } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

const DEFAULT_CONTEXT = {
  product_validation: { estimated_monthly_searches: 12000, competition_level: "low" },
  supplier_sourcing: { unit_cost: 5.0, lead_time_days: 20, supplier_verified: true },
  finance_validation: { unit_cost: 5.0, sale_price: 20.0, monthly_unit_sales: 300, monthly_fixed_costs: 500.0 },
  legal_validation: { restricted_category: false, requires_certification: false, certification_available: true },
  requests_simulated_spend: true,
  spend_action: "launch_marketing_campaign",
  spend_amount: 150.0,
};

const MARKET_OPTIONS = ["España y UE", "España", "Unión Europea", "Global"];
const PRIORITY_OPTIONS = ["Baja", "Media", "Alta"];
const ANALYSIS_TYPE_OPTIONS = [
  "Validación de producto",
  "Análisis de mercado",
  "Auditoría de proveedor",
  "Revisión legal",
];
const DEFAULT_SPECIFIC_GOALS = [
  "Analizar demanda y tendencia",
  "Encontrar proveedores competitivos",
  "Evaluar margen y rentabilidad",
  "Revisar requisitos legales y de seguridad",
];

const DRAFT_STORAGE_KEY = "amazona.ceo.draft";

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

function CollapsibleRow({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 py-2.5 text-left text-sm font-medium hover:text-primary"
      >
        {title}
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open ? <div className="pb-3 text-sm text-muted-foreground">{children}</div> : null}
    </div>
  );
}

function CeoForm() {
  const searchParams = useSearchParams();
  const initial = buildInitialState(searchParams);

  const [title, setTitle] = useState(initial.title);
  const [createdBy, setCreatedBy] = useState("owner@amazona.local");
  const [description, setDescription] = useState(
    "Analizar la viabilidad comercial, proveedores, costes, competencia y requisitos legales para la venta del producto. Priorizar bajo riesgo y alta demanda sostenible.",
  );
  const [market, setMarket] = useState(MARKET_OPTIONS[0]);
  const [priority, setPriority] = useState(PRIORITY_OPTIONS[1]);
  const [analysisType, setAnalysisType] = useState(ANALYSIS_TYPE_OPTIONS[0]);
  const [specificGoals, setSpecificGoals] = useState<{ label: string; checked: boolean }[]>(
    DEFAULT_SPECIFIC_GOALS.map((label) => ({ label, checked: true })),
  );
  const [newGoal, setNewGoal] = useState("");
  const [context, setContext] = useState(JSON.stringify(initial.context, null, 2));
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [executions, setExecutions] = useState<AgentExecution[]>([]);
  const [agentsById, setAgentsById] = useState<Map<string, Agent>>(new Map());

  function toggleGoal(index: number) {
    setSpecificGoals((goals) => goals.map((g, i) => (i === index ? { ...g, checked: !g.checked } : g)));
  }

  function removeGoal(index: number) {
    setSpecificGoals((goals) => goals.filter((_, i) => i !== index));
  }

  function addGoal() {
    const label = newGoal.trim();
    if (!label) return;
    setSpecificGoals((goals) => [...goals, { label, checked: true }]);
    setNewGoal("");
  }

  function saveDraft() {
    try {
      const draft = { title, createdBy, description, market, priority, analysisType, specificGoals, context };
      window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
      setDraftSavedAt(new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }));
    } catch {
      setError("No se pudo guardar el borrador en este navegador.");
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    let parsedContext: Record<string, unknown>;
    try {
      parsedContext = JSON.parse(context);
    } catch {
      setError("El contexto debe ser JSON válido.");
      return;
    }

    parsedContext = {
      ...parsedContext,
      brief: {
        market,
        priority,
        analysis_type: analysisType,
        specific_goals: specificGoals.filter((g) => g.checked).map((g) => g.label),
      },
    };

    setSubmitting(true);
    setRunResult(null);
    setDecision(null);
    setExecutions([]);
    try {
      const objective = await api.createObjective({
        title,
        description,
        created_by: createdBy,
        context: parsedContext,
      });
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
      setError(err instanceof ApiError ? err.message : "No se pudo ejecutar este objetivo.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Director ejecutivo"
          description="Centro de orquestación multiagente: un objetivo entra por CEO, se reparte entre los agentes especializados y el Decision Engine sintetiza la decisión. Simulado — sin dinero, pedidos ni proveedores reales."
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Nuevo objetivo</CardTitle>
            <StatusChip status="DRAFT" />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="title" className="text-sm font-medium">
                Título del objetivo
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

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="description" className="text-sm font-medium">
                  Descripción / contexto
                </label>
                <span className="text-xs text-muted-foreground">{description.length}/1000</span>
              </div>
              <textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value.slice(0, 1000))}
                rows={4}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <label htmlFor="market" className="text-sm font-medium">
                  Mercado objetivo
                </label>
                <select
                  id="market"
                  value={market}
                  onChange={(e) => setMarket(e.target.value)}
                  className="w-full rounded-md border bg-background px-2 py-2 text-sm"
                >
                  {MARKET_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="priority" className="text-sm font-medium">
                  Prioridad
                </label>
                <select
                  id="priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  className="w-full rounded-md border bg-background px-2 py-2 text-sm"
                >
                  {PRIORITY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="analysisType" className="text-sm font-medium">
                  Tipo de análisis
                </label>
                <select
                  id="analysisType"
                  value={analysisType}
                  onChange={(e) => setAnalysisType(e.target.value)}
                  className="w-full rounded-md border bg-background px-2 py-2 text-sm"
                >
                  {ANALYSIS_TYPE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-1.5">
              <p className="text-sm font-medium">Objetivos específicos (opcional)</p>
              <ul className="space-y-1.5">
                {specificGoals.map((goal, index) => (
                  <li key={`${goal.label}-${index}`} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={goal.checked}
                      onChange={() => toggleGoal(index)}
                      className="size-4 rounded border-border accent-primary"
                    />
                    <span className={cn("flex-1", !goal.checked && "text-muted-foreground line-through")}>
                      {goal.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeGoal(index)}
                      aria-label={`Quitar "${goal.label}"`}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <X className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex gap-2 pt-1">
                <input
                  value={newGoal}
                  onChange={(e) => setNewGoal(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addGoal();
                    }
                  }}
                  placeholder="Añadir objetivo específico"
                  className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
                />
                <Button type="button" variant="outline" size="sm" onClick={addGoal}>
                  <Plus className="size-3.5" />
                  Añadir
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

      </div>

      <Card>
        <CardHeader>
          <CardTitle>Grafo de agentes</CardTitle>
        </CardHeader>
        <CardContent>
          <NeuralNexusGraph decision={decision} />
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
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Configuración avanzada</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <p className="mb-2 text-xs text-muted-foreground">
                Parámetros y datos simulados. El flujo normal no requiere tocar JSON.
              </p>
              <CollapsibleRow title="Contexto técnico (JSON)">
                <textarea
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  rows={10}
                  className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs text-foreground"
                />
                <p className="mt-2 text-xs">
                  Valores fijos que recibe cada agente especializado — sin dinero, pedidos ni proveedores reales.
                </p>
              </CollapsibleRow>
              <CollapsibleRow title="Fuentes de datos">
                <div className="flex flex-wrap gap-2">
                  <DataProvenanceBadge status="estimated" tooltip="Búsquedas, competencia y demanda: estimación AMAZONA." />
                  <DataProvenanceBadge status="pending" tooltip="Proveedores y costes reales: pendiente de integrar con SP-API." />
                </div>
              </CollapsibleRow>
              <CollapsibleRow title="Restricciones y supuestos">
                <ul className="list-disc space-y-1 pl-4">
                  <li>Sin gasto, pedidos ni proveedores reales — todo simulado.</li>
                  <li>La decisión final la sintetiza el Decision Engine, no un solo agente.</li>
                  <li>Cualquier bloqueo legal o financiero fuerza NO_GO o revisión humana.</li>
                </ul>
              </CollapsibleRow>
              <CollapsibleRow title="Parámetros de agentes">
                <p>
                  4 agentes especializados participan en esta ejecución (Product Hunter, Supplier Finder, CFO/Finanzas,
                  Legal). Market Analyst, Marketing y E-commerce se incorporan en el pipeline de Fase 3.
                </p>
              </CollapsibleRow>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resumen de la misión</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Agentes implicados</span>
                <span className="font-medium">4 + Decision Engine</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Ejecución estimada</span>
                <DataProvenanceBadge status="estimated" tooltip="Duración típica de esta simulación, no una garantía." />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Coste</span>
                <span className="font-medium">Sin coste (simulado)</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Riesgo estimado</span>
                <span className="font-medium">{priority === "Alta" ? "Medio" : "Bajo"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Resultado esperado</span>
                <span className="font-medium">Decisión GO/NO_GO + informe</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Notificaciones</span>
                <span className="font-medium">Al completar</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Acciones</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2.5">
              {error ? (
                <Alert variant="destructive">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>No se pudo ejecutar este objetivo</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}

              <Button type="submit" disabled={submitting} className="w-full">
                {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
                {submitting ? "Ejecutando…" : "Ejecutar objetivo"}
              </Button>
              <Button type="button" variant="outline" className="w-full" onClick={saveDraft}>
                <Save className="size-4" />
                Guardar borrador
              </Button>
              <Button type="button" variant="ghost" className="w-full" disabled title="Próximamente">
                Programar ejecución
              </Button>
              {draftSavedAt ? (
                <p className="text-center text-xs text-muted-foreground">Borrador guardado a las {draftSavedAt}.</p>
              ) : null}
            </CardContent>
          </Card>
        </div>
      )}
    </form>
  );
}

export default function CeoPage() {
  return (
    <Suspense fallback={null}>
      <CeoForm />
    </Suspense>
  );
}
