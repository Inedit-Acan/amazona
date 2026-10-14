"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { AlertTriangle, ChevronDown, Loader2, Plus, Save, X } from "lucide-react";
import { useCeo } from "@/components/ceo/ceo-context";
import { DataProvenanceBadge } from "@/components/data-provenance-badge";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api, ApiError, type RunResult } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { MissionInitialState } from "@/lib/ceo-handoff";
import { missionOutcome, NOT_AVAILABLE, type MissionOutcome } from "@/lib/ceo-mission-view";
import { OPERATIONS } from "@/lib/intent-operations";
import { readErrorText, readList } from "@/lib/read-state";
import { settle } from "@/lib/revenue-view";
import { useIntent } from "@/lib/use-intent";
import { cn } from "@/lib/utils";

// El formulario de misión del Director ejecutivo (M47, Commit 2). Es el de `app/ceo/page.tsx` —la lógica de creación y
// ejecución, con su clave de intención, NO cambia—, movido a un drawer. Cambios deliberados:
//   · empieza vacío: ya no precarga un título ni un solicitante inventados («Validate wireless earbuds opportunity»,
//     «owner@amazona.local», que acababa en el registro de auditoría como actor);
//   · sin la tarjeta «Resumen de la misión» previa (filas fijas inventadas) ni el texto «4 agentes…»;
//   · tras ejecutar, las lecturas de la decisión, las ejecuciones y los agentes ya no se tragan con `.catch(() => [])`: cada una
//     trae su estado y el resumen dice «No disponible» en lo que no se pudo leer (lib/ceo-mission-view.ts).

const MARKET_OPTIONS = ["España y UE", "España", "Unión Europea", "Global"];
const PRIORITY_OPTIONS = ["Baja", "Media", "Alta"];
const ANALYSIS_TYPE_OPTIONS = ["Validación de producto", "Análisis de mercado", "Auditoría de proveedor", "Revisión legal"];
const DEFAULT_SPECIFIC_GOALS = [
  "Analizar demanda y tendencia",
  "Encontrar proveedores competitivos",
  "Evaluar margen y rentabilidad",
  "Revisar requisitos legales y de seguridad",
];
const DEFAULT_DESCRIPTION =
  "Analizar la viabilidad comercial, proveedores, costes, competencia y requisitos legales para la venta del producto. Priorizar bajo riesgo y alta demanda sostenible.";

const DRAFT_STORAGE_KEY = "amazona.ceo.draft";

const DECISION_STATUS_LABEL: Record<string, string> = {
  GO: "Favorable (GO)",
  NO_GO: "No viable (NO_GO)",
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
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 py-2.5 text-left text-sm font-medium hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {title}
        <ChevronDown aria-hidden className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open ? <div className="pb-3 text-sm text-muted-foreground">{children}</div> : null}
    </div>
  );
}

/** El estado y las acciones de la misión. Vive en el drawer (siempre montado) y no en el formulario, para que cerrar el drawer
 * por error no pierda lo escrito. */
export function useMission(initial: MissionInitialState) {
  const { setDecision } = useCeo();
  const [title, setTitle] = useState(initial.title);
  const [createdBy, setCreatedBy] = useState("");
  const [description, setDescription] = useState(DEFAULT_DESCRIPTION);
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
  const intent = useIntent("ceo");
  // El objetivo ya creado para esta misma petición: un reintento corre **ese**, no crea otro y otra clave.
  const createdObjective = useRef<{ brief: string; id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [outcome, setOutcome] = useState<MissionOutcome | null>(null);

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

  async function submit(event: React.FormEvent) {
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
    setOutcome(null);
    setDecision({ kind: "none" });
    try {
      const brief = { title, description, created_by: createdBy.trim(), context: parsedContext };
      const result = await intent.run(
        { operation: OPERATIONS.objectiveRun, target: "ceo-brief", params: brief },
        async (key) => {
          const wanted = JSON.stringify(brief);
          if (createdObjective.current?.brief !== wanted) {
            const created = await api.createObjective(brief);
            createdObjective.current = { brief: wanted, id: created.id };
          }
          return api.runObjective(createdObjective.current.id, { idempotencyKey: key });
        },
      );
      createdObjective.current = null; // terminó: la próxima petición es otra
      setRunResult(result);

      // Lo que se enseña de la misión ya ejecutada se lee ahora; cada lectura trae su estado y NINGUNA se traga.
      const [decision, executions, agents] = await Promise.all([
        settle(() => api.getDecision(result.id), (status) => readErrorText(status, "la decisión")),
        readList(() => api.listAgentExecutions(), "el log de ejecuciones"),
        readList(() => api.listAgents(), "los agentes"),
      ]);
      const view = missionOutcome({ correlationId: result.correlation_id, decision, executions, agents });
      setOutcome(view);
      setDecision(view.decision);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo ejecutar este objetivo.");
    } finally {
      setSubmitting(false);
    }
  }

  return {
    title, setTitle,
    createdBy, setCreatedBy,
    description, setDescription,
    market, setMarket,
    priority, setPriority,
    analysisType, setAnalysisType,
    specificGoals, toggleGoal, removeGoal,
    newGoal, setNewGoal, addGoal,
    context, setContext,
    draftSavedAt, saveDraft,
    submitting, submit,
    error,
    runResult, outcome,
  };
}

export type Mission = ReturnType<typeof useMission>;

const FIELD = "w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none";

export function MissionForm({ mission }: { mission: Mission }) {
  const m = mission;
  return (
    <div className="space-y-5">
      <form onSubmit={m.submit} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="mission-title" className="text-sm font-medium">
            Título del objetivo
          </label>
          <input
            id="mission-title"
            value={m.title}
            onChange={(e) => m.setTitle(e.target.value)}
            required
            placeholder="Ej.: validar el producto X"
            className={FIELD}
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="mission-created-by" className="text-sm font-medium">
            Solicitado por <span className="font-normal text-muted-foreground">(opcional)</span>
          </label>
          <input
            id="mission-created-by"
            value={m.createdBy}
            onChange={(e) => m.setCreatedBy(e.target.value)}
            placeholder="Si lo dejas vacío, el backend usa tu sesión"
            className={FIELD}
          />
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="mission-description" className="text-sm font-medium">
              Descripción / contexto
            </label>
            <span className="text-xs text-muted-foreground">{m.description.length}/1000</span>
          </div>
          <textarea
            id="mission-description"
            value={m.description}
            onChange={(e) => m.setDescription(e.target.value.slice(0, 1000))}
            rows={4}
            className={FIELD}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <label htmlFor="mission-market" className="text-sm font-medium">
              Mercado objetivo
            </label>
            <select id="mission-market" value={m.market} onChange={(e) => m.setMarket(e.target.value)} className={cn(FIELD, "px-2")}>
              {MARKET_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="mission-priority" className="text-sm font-medium">
              Prioridad
            </label>
            <select id="mission-priority" value={m.priority} onChange={(e) => m.setPriority(e.target.value)} className={cn(FIELD, "px-2")}>
              {PRIORITY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="mission-analysis" className="text-sm font-medium">
              Tipo de análisis
            </label>
            <select id="mission-analysis" value={m.analysisType} onChange={(e) => m.setAnalysisType(e.target.value)} className={cn(FIELD, "px-2")}>
              {ANALYSIS_TYPE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
        </div>

        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">Objetivos específicos (opcional)</legend>
          <ul className="space-y-1.5">
            {m.specificGoals.map((goal, index) => (
              <li key={`${goal.label}-${index}`} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={goal.checked}
                  onChange={() => m.toggleGoal(index)}
                  aria-label={goal.label}
                  className="size-4 rounded border-border accent-primary"
                />
                <span className={cn("flex-1", !goal.checked && "text-muted-foreground line-through")}>{goal.label}</span>
                <button
                  type="button"
                  onClick={() => m.removeGoal(index)}
                  aria-label={`Quitar "${goal.label}"`}
                  className="rounded-sm text-muted-foreground hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <X aria-hidden className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-2 pt-1">
            <input
              value={m.newGoal}
              onChange={(e) => m.setNewGoal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  m.addGoal();
                }
              }}
              aria-label="Añadir objetivo específico"
              placeholder="Añadir objetivo específico"
              className={cn(FIELD, "py-1.5")}
            />
            <Button type="button" variant="outline" size="sm" onClick={m.addGoal}>
              <Plus aria-hidden className="size-3.5" />
              Añadir
            </Button>
          </div>
        </fieldset>

        <div className="rounded-lg border px-3">
          <p className="pt-2.5 text-xs text-muted-foreground">Parámetros y datos simulados. El flujo normal no requiere tocar JSON.</p>
          <CollapsibleRow title="Contexto técnico (JSON)">
            <label htmlFor="mission-context" className="sr-only">
              Contexto técnico en JSON
            </label>
            <textarea
              id="mission-context"
              value={m.context}
              onChange={(e) => m.setContext(e.target.value)}
              rows={10}
              className="w-full rounded-md border bg-background px-3 py-2 font-mono text-xs text-foreground"
            />
            <p className="mt-2 text-xs">
              Datos de ejemplo que recibe cada agente especializado — sin dinero, pedidos ni proveedores reales.
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
        </div>

        {m.error ? (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>No se pudo ejecutar este objetivo</AlertTitle>
            <AlertDescription>{m.error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={m.submitting}>
            {m.submitting ? <Loader2 aria-hidden className="size-4 animate-spin" /> : null}
            {m.submitting ? "Ejecutando…" : "Ejecutar objetivo"}
          </Button>
          <Button type="button" variant="outline" onClick={m.saveDraft}>
            <Save aria-hidden className="size-4" />
            Guardar borrador
          </Button>
          <Button type="button" variant="ghost" disabled title="Próximamente">
            Programar ejecución
          </Button>
        </div>
        {m.draftSavedAt ? <p className="text-xs text-muted-foreground">Borrador guardado a las {m.draftSavedAt}.</p> : null}
      </form>

      {m.runResult ? <MissionResult mission={m} /> : null}
    </div>
  );
}

function MissionResult({ mission }: { mission: Mission }) {
  const result = mission.runResult!;
  const outcome = mission.outcome;
  return (
    <section aria-label="Resumen de misión" className="space-y-4 rounded-xl border p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Resumen de misión</h3>
        <StatusChip status={result.status} />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Resultado</p>
          <p className="font-medium">{DECISION_STATUS_LABEL[result.status] ?? result.status}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Confianza</p>
          <p className="font-medium">{result.confidence != null ? result.confidence.toFixed(2) : "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Score de oportunidad</p>
          <p className="font-medium">{result.opportunity_score != null ? result.opportunity_score.toFixed(2) : "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Agentes ejecutados</p>
          <p className="font-medium">
            {outcome === null ? "Leyendo…" : outcome.executed.kind === "value" ? outcome.executed.count : outcome.executed.text}
          </p>
        </div>
      </div>

      {result.rationale ? <p className="text-sm text-muted-foreground">{result.rationale}</p> : null}

      {outcome?.decisionNote ? (
        <Alert>
          <AlertTriangle className="size-4" />
          <AlertTitle>Decisión no disponible</AlertTitle>
          <AlertDescription>{outcome.decisionNote}</AlertDescription>
        </Alert>
      ) : null}

      {outcome && outcome.executed.kind === "unavailable" ? (
        <p className="text-xs text-muted-foreground">
          No se pudo leer el log de ejecuciones: no se sabe cuántos agentes participaron ({NOT_AVAILABLE}).
        </p>
      ) : null}

      {outcome && outcome.rows.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">Vista previa de ejecución</p>
          <ul className="divide-y rounded-md border">
            {outcome.rows.map((row) => (
              <li key={row.id} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium">{row.agent}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {row.capability.replace(/_/g, " ")} · {formatDuration(row.durationMs)}
                  </p>
                </div>
                <StatusChip status={row.success ? "COMPLETED" : "FAILED"} />
              </li>
            ))}
          </ul>
          {outcome.agentNamesUnavailable ? (
            <p className="mt-1 text-xs text-muted-foreground">No se pudieron leer los agentes: se enseña su identificador.</p>
          ) : null}
        </div>
      ) : null}

      <Button size="sm" variant="outline" nativeButton={false} render={<Link href={`/projects/${result.project_id}`} />}>
        Ver proyecto
      </Button>
    </section>
  );
}
