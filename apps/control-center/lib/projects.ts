import type { Decision, DecisionStatus, Project, ProjectStatus, Task } from "./api.ts";

// Un proyecto es una validación de producto orquestada por el CEO: un grafo de
// tareas de especialistas y una decisión con evidencias (ceo/orchestrator.py).
// No está enlazado a producto, mercado, ventas ni beneficio. Este módulo solo
// ordena, agrupa y reexpresa lo que ya devolvió el backend.

export type ProjectGroup = "validation" | "active" | "rejected" | "other";

const GROUP_BY_STATUS: Record<ProjectStatus, ProjectGroup> = {
  DRAFT: "validation",
  VALIDATING: "validation",
  APPROVED: "active",
  EXECUTING: "active",
  MONITORING: "active",
  REJECTED: "rejected",
  FAILED: "rejected",
  PAUSED: "other",
  COMPLETED: "other",
};

export function projectGroup(status: ProjectStatus): ProjectGroup {
  return GROUP_BY_STATUS[status] ?? "other";
}

export const GROUP_LABELS: Record<ProjectGroup, string> = {
  validation: "En validación",
  active: "Activos",
  rejected: "Rechazados",
  other: "Otros",
};

export function countByGroup(projects: Pick<Project, "status">[]): Record<ProjectGroup, number> {
  const counts: Record<ProjectGroup, number> = { validation: 0, active: 0, rejected: 0, other: 0 };
  for (const project of projects) counts[projectGroup(project.status)] += 1;
  return counts;
}

export interface TaskProgress {
  done: number;
  total: number;
  /** 0-1; 0 si el proyecto aún no tiene tareas. */
  ratio: number;
}

/** Progreso = tareas completadas sobre las del grafo del proyecto. */
export function taskProgress(tasks: Pick<Task, "status">[]): TaskProgress {
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "COMPLETED").length;
  return { done, total, ratio: total > 0 ? done / total : 0 };
}

export interface TaskCounts {
  running: number;
  waiting: number;
  pending: number;
  completed: number;
  failed: number;
}

/** Tareas por situación: ejecutando, en espera, pendientes, completadas y fallidas o bloqueadas. */
export function taskCounts(tasks: Pick<Task, "status">[]): TaskCounts {
  const counts: TaskCounts = { running: 0, waiting: 0, pending: 0, completed: 0, failed: 0 };
  for (const { status } of tasks) {
    if (status === "RUNNING" || status === "QUEUED") counts.running += 1;
    else if (status === "WAITING" || status === "WAITING_APPROVAL") counts.waiting += 1;
    else if (status === "COMPLETED") counts.completed += 1;
    else if (status === "FAILED" || status === "BLOCKED" || status === "CANCELLED") counts.failed += 1;
    else counts.pending += 1;
  }
  return counts;
}

export interface PipelineStage {
  /** Nombre de la tarea del grafo (y `source` de la evidencia de la decisión). */
  task: string;
  label: string;
  href: string;
}

/** Las cuatro fases que el CEO puede evidenciar por proyecto, enlazadas al módulo
 * que las trabaja. Tienda, Marketing, Operaciones y Escala no cuelgan del proyecto. */
export const PIPELINE_STAGES: PipelineStage[] = [
  { task: "product_validation", label: "Investigación", href: "/research" },
  { task: "supplier_sourcing", label: "Proveedores", href: "/sourcing" },
  { task: "finance_validation", label: "Economía", href: "/economics" },
  { task: "legal_validation", label: "Legal", href: "/legal" },
];

export const UNLINKED_STAGES = ["Tienda", "Marketing", "Operaciones", "Escala"];

export type StageState = "done" | "current" | "blocked" | "todo";

export interface PipelineStep extends PipelineStage {
  state: StageState;
  /** GO / REVIEW / NO_GO de la evidencia de esa fase, si la decisión ya la trae. */
  recommendation: string | null;
}

function stateOf(task: Pick<Task, "status"> | undefined): StageState {
  if (!task) return "todo";
  if (task.status === "COMPLETED") return "done";
  if (task.status === "FAILED" || task.status === "BLOCKED" || task.status === "CANCELLED") return "blocked";
  if (task.status === "RUNNING" || task.status === "QUEUED" || task.status === "WAITING" || task.status === "WAITING_APPROVAL")
    return "current";
  return "todo";
}

export function pipelineSteps(
  tasks: Pick<Task, "name" | "status">[],
  decision: Pick<Decision, "evidence"> | null,
): PipelineStep[] {
  return PIPELINE_STAGES.map((stage) => {
    const evidence = decision?.evidence.find((e) => e.source === stage.task);
    const recommendation = evidence?.data?.recommendation;
    return {
      ...stage,
      state: stateOf(tasks.find((t) => t.name === stage.task)),
      recommendation: typeof recommendation === "string" ? recommendation : null,
    };
  });
}

export interface ProjectRisk {
  stage: string;
  risk: string;
}

/** Riesgos que cada especialista dejó en la evidencia de la decisión. */
export function projectRisks(decision: Pick<Decision, "evidence"> | null): ProjectRisk[] {
  if (!decision) return [];
  return decision.evidence.flatMap((evidence) => {
    const stage = PIPELINE_STAGES.find((s) => s.task === evidence.source)?.label ?? evidence.source;
    const risks = evidence.data?.risks;
    return Array.isArray(risks) ? risks.filter((r): r is string => typeof r === "string").map((risk) => ({ stage, risk })) : [];
  });
}

export interface ProjectedFinance {
  /** Beneficio mensual que calculó el especialista de finanzas con los supuestos del objetivo. */
  monthlyProfit: number;
  margin: number | null;
}

/** Lectura estructurada de la evidencia `finance_validation` de la decisión (no se
 * parsea el texto del resumen). Son supuestos de simulación del objetivo, no ventas reales. */
export function projectedFinance(decision: Pick<Decision, "evidence"> | null): ProjectedFinance | null {
  const data = decision?.evidence.find((e) => e.source === "finance_validation")?.data;
  const monthlyProfit = data?.monthly_profit;
  if (typeof monthlyProfit !== "number") return null;
  const margin = data?.margin;
  return { monthlyProfit, margin: typeof margin === "number" ? margin : null };
}

export interface Milestone {
  label: string;
  done: boolean;
}

/** Hitos que sí se pueden leer del grafo de tareas del proyecto. */
export function milestones(tasks: Pick<Task, "name" | "status">[]): Milestone[] {
  const done = (name: string) => tasks.find((t) => t.name === name)?.status === "COMPLETED";
  return [
    { label: "Producto validado", done: done("product_validation") },
    { label: "Proveedor seleccionado", done: done("supplier_sourcing") },
    { label: "Viabilidad económica", done: done("finance_validation") },
    { label: "Legal Gate", done: done("legal_validation") },
    { label: "Decisión del director ejecutivo", done: done("decision_synthesis") },
  ];
}

export interface DecisionVerdict {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "bad";
}

/** Estado de la decisión del director ejecutivo, en lenguaje llano. */
export const DECISION_VERDICT: Record<DecisionStatus, DecisionVerdict> = {
  GO: { title: "Aprobada", detail: "Todas las validaciones pasan: el proyecto puede avanzar.", tone: "ok" },
  REVIEW: {
    title: "Requiere revisión",
    detail: "Falta información o alguna validación pide revisión antes de decidir.",
    tone: "warn",
  },
  HUMAN_APPROVAL: {
    title: "Espera una aprobación humana",
    detail: "El gasto o la acción propuesta necesita que una persona la autorice en Aprobaciones.",
    tone: "warn",
  },
  NO_GO: { title: "Rechazada", detail: "Alguna validación bloquea el proyecto.", tone: "bad" },
};
