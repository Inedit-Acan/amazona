import type { PipelineRun, PipelineRunStatus, PipelineStep } from "./api.ts";

// Vista de las ejecuciones del pipeline para el panel Estado (Milestone 32).
//
// Igual que la tarjeta del runtime de trabajos, aquí NO hay datos de
// demostración: o el backend responde las ejecuciones, o no se enseña nada. Una
// ejecución inventada diría que el sistema está descubriendo productos cuando no
// lo está.
//
// Desde el Milestone 32 una ejecución no es un resultado sino un proceso: se
// encola, un worker la recorre paso a paso, y puede quedarse parada de cuatro
// maneras distintas que significan cosas distintas.

/** Los nueve pasos, en el único orden en que pueden ocurrir. */
export const STEP_ORDER = [
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

export const RUN_STATUS_LABEL: Record<PipelineRunStatus, string> = {
  QUEUED: "En cola",
  RUNNING: "Ejecutando",
  COMPLETED: "Completada",
  PARTIAL: "Incompleta",
  FAILED: "Fallida",
  BLOCKED: "Bloqueada",
  CANCELLED: "Cancelada",
};

export const STEP_LABEL: Record<string, string> = {
  research: "Investigación",
  sourcing: "Proveedores",
  economics: "Economía",
  legal: "Legal",
  ecommerce: "Tienda",
  marketplace: "Marketplace",
  marketing: "Marketing",
  operations: "Operaciones",
  cfo: "CFO",
};

/** Ejecuciones que el sistema va a mover por su cuenta. */
export const RUNNING_STATUSES: PipelineRunStatus[] = ["QUEUED", "RUNNING"];

/** Ejecuciones paradas que nadie va a continuar salvo que una persona lo pida.
 * `FAILED` no entra aquí: el runtime la reintenta sola mientras le queden
 * intentos, y distinguirlo es justamente lo que evita una alarma falsa. */
export const STOPPED_STATUSES: PipelineRunStatus[] = ["BLOCKED", "CANCELLED"];

export interface PipelineCounts {
  queued: number;
  running: number;
  completed: number;
  partial: number;
  failed: number;
  blocked: number;
  cancelled: number;
}

const EMPTY: PipelineCounts = {
  queued: 0,
  running: 0,
  completed: 0,
  partial: 0,
  failed: 0,
  blocked: 0,
  cancelled: 0,
};

const KEY: Record<PipelineRunStatus, keyof PipelineCounts> = {
  QUEUED: "queued",
  RUNNING: "running",
  COMPLETED: "completed",
  PARTIAL: "partial",
  FAILED: "failed",
  BLOCKED: "blocked",
  CANCELLED: "cancelled",
};

export function pipelineCounts(runs: PipelineRun[]): PipelineCounts {
  const counts = { ...EMPTY };
  for (const run of runs) {
    const key = KEY[run.status];
    if (key) counts[key] += 1;
  }
  return counts;
}

export interface StepProgress {
  /** Pasos terminados bien. */
  completed: number;
  /** Los nueve, siempre: una ejecución tiene sus nueve pasos desde que nace. */
  total: number;
  /** El paso que está en marcha, o el que dejó la ejecución parada. */
  current: string | null;
  currentStatus: string | null;
}

/** Por dónde va una ejecución. El paso «actual» es el que se está ejecutando; si
 * ninguno lo está, el primero que no ha terminado — que es donde continuaría. */
export function stepProgress(run: PipelineRun): StepProgress {
  const entries: [string, PipelineStep][] = [];
  for (const name of STEP_ORDER) {
    const value = run.steps[name];
    if (value !== undefined) entries.push([name, value]);
  }
  const completed = entries.filter(([, step]) => step.step_status === "COMPLETED").length;
  const running = entries.find(([, step]) => step.step_status === "RUNNING");
  const pending = entries.find(([, step]) => step.step_status !== "COMPLETED");
  const current = running ?? pending ?? null;
  return {
    completed,
    total: entries.length || STEP_ORDER.length,
    current: current ? current[0] : null,
    currentStatus: current ? current[1].step_status : null,
  };
}

/** El error que explica por qué una ejecución está parada, si lo hay. */
export function runError(run: PipelineRun): string | null {
  if (run.failed_step) {
    const step = run.steps[run.failed_step];
    if (step?.error) return step.error;
  }
  const failed = STEP_ORDER.map((name) => run.steps[name]).find((step) => step?.error);
  return failed?.error ?? null;
}

export interface PipelineRunRow {
  correlationId: string;
  category: string;
  market: string;
  status: PipelineRunStatus;
  progress: StepProgress;
  needsReview: boolean;
  error: string | null;
  jobId: string | null;
}

export function pipelineRunRows(runs: PipelineRun[], limit = 6): PipelineRunRow[] {
  return runs.slice(0, limit).map((run) => ({
    correlationId: run.correlation_id,
    category: run.category,
    market: run.market,
    status: run.status,
    progress: stepProgress(run),
    needsReview: run.needs_review,
    error: runError(run),
    jobId: run.job_id,
  }));
}

export interface PipelineVerdict {
  tone: "ok" | "warning" | "error";
  headline: string;
  detail: string;
}

/** Qué decir del pipeline en una línea.
 *
 * El orden importa y no es arbitrario: una ejecución parada por el kill switch o
 * por una cancelación no se va a mover nunca sola, así que pesa más que una que
 * falló —esa el runtime la reintenta— y más que una en cola. */
export function pipelineVerdict(counts: PipelineCounts): PipelineVerdict {
  const stopped = counts.blocked + counts.cancelled;
  if (counts.blocked > 0) {
    return {
      tone: "error",
      headline: `${counts.blocked} ${counts.blocked === 1 ? "ejecución bloqueada" : "ejecuciones bloqueadas"}`,
      detail: "El kill switch estaba apagado cuando les tocó. Reactívalo y reanúdalas.",
    };
  }
  if (counts.failed > 0) {
    return {
      tone: "warning",
      headline: `${counts.failed} ${counts.failed === 1 ? "ejecución con un paso fallido" : "ejecuciones con un paso fallido"}`,
      detail: "Se reintentan solas mientras les queden intentos; si se agotan, hay que reanudarlas.",
    };
  }
  if (counts.partial > 0) {
    return {
      tone: "warning",
      headline: `${counts.partial} ${counts.partial === 1 ? "ejecución incompleta" : "ejecuciones incompletas"}`,
      detail: "Un paso no pudo entregar nada al siguiente. Están en la bandeja de revisión.",
    };
  }
  if (counts.running + counts.queued > 0) {
    return {
      tone: "ok",
      headline: `${counts.running + counts.queued} en curso`,
      detail: "El pipeline está trabajando fuera de la petición HTTP.",
    };
  }
  if (stopped > 0) {
    return {
      tone: "warning",
      headline: `${stopped} ${stopped === 1 ? "ejecución cancelada" : "ejecuciones canceladas"}`,
      detail: "Paradas a mano. No vuelven solas: hay que reanudarlas.",
    };
  }
  if (counts.completed > 0) {
    return {
      tone: "ok",
      headline: `${counts.completed} ${counts.completed === 1 ? "ejecución completada" : "ejecuciones completadas"}`,
      detail: "Nada pendiente de ejecutar.",
    };
  }
  return { tone: "ok", headline: "Sin ejecuciones", detail: "Todavía no se ha encolado ninguna." };
}
