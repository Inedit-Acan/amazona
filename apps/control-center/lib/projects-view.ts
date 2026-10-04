import type { AuditEntry, Decision, DecisionStatus, Project, ProjectStatus, Task } from "./api.ts";
import { planned, type Planned } from "./provenance.ts";
import { NO_DATA, UNREAD } from "./revenue-view.ts";
import {
  DECISION_VERDICT,
  pipelineSteps,
  projectRisks as risksFromDecision,
  projectedFinance,
  taskProgress,
  type PipelineStep,
  type ProjectRisk,
  type TaskProgress,
} from "./projects.ts";

// Vista de la pantalla de Proyectos (M45, Commit 11).
//
// Un proyecto es lo que el backend llama proyecto: una validación de producto que el Director ejecutivo orquestó, con
// su grafo de tareas y su decisión (`ceo/orchestrator.py`). **Un producto del catálogo no es un proyecto**: un pedido
// puede contener varios productos y no existe ninguna regla aprobada para repartir su ingreso, así que esta pantalla
// no convierte productos, oportunidades, análisis ni señales en proyectos. Si no hay proyectos reales, lo dice.
//
// Hasta el Commit 10 esta vista FABRICABA la cartera: cada producto se presentaba como un proyecto, once proyectos más
// salían de `lib/demo/projects.ts`, y el «Beneficio real» de cada uno se calculaba con `buildOrders()` —pedidos
// GENERADOS— y se sumaba en un KPI de cabecera. Nada de eso existía. Lo que queda aquí sale del backend o se declara
// ausente:
//
//   `project.status`              el estado que el backend guarda, no uno derivado
//   las cuatro etapas del grafo   con el estado real de su tarea y la recomendación de su evidencia
//   `taskProgress`                tareas completadas sobre las del grafo
//   la decisión                   veredicto, confianza y riesgos que dejaron los especialistas
//   la proyección (PLAN)          `finance_validation.monthly_profit`, y `null` cuando el agente no la pudo calcular
//   la fecha de inicio            la entrada de auditoría `project.created`, y `null` cuando no está registrada
//
// Lo que no tiene fuente no se estima, no se rellena con una constante y no se sustituye por cero: se dice
// «Sin datos» y se explica por qué (`NOT_CALCULATED`).

/** Prefijo del código con el que Aprobaciones, el Panel y Auditoría se refieren a un producto del catálogo. */
export const PROJECT_CODE_PREFIX = "AMZ-";

/** Código de un producto del catálogo por su posición (AMZ-0024, AMZ-0023…). Lo usan Aprobaciones, el Panel y
 * Auditoría, y **no cambia en este commit**. Deuda conocida: ese código habla de productos, no de proyectos, y dejará
 * de llamarse «código de proyecto» cuando exista un modelo de relación real entre producto y proyecto. */
export function projectCodeFor(index: number): string {
  return `${PROJECT_CODE_PREFIX}${String(24 - index).padStart(4, "0")}`;
}

// --- El estado del proyecto, tal como lo guarda el backend ---------------------------------------------------------

/** Cómo se lee en pantalla cada `Project.status`. Son los estados del backend, no una clasificación nuestra. */
export const PROJECT_STATUS_LABEL: Record<ProjectStatus, string> = {
  DRAFT: "Borrador",
  VALIDATING: "En validación",
  APPROVED: "Aprobado",
  EXECUTING: "En ejecución",
  MONITORING: "En seguimiento",
  PAUSED: "Pausado",
  COMPLETED: "Completado",
  REJECTED: "Rechazado",
  FAILED: "Fallido",
};

export type PortfolioGroup = "validation" | "execution" | "paused" | "closed";

/** A qué bloque pertenece cada estado del backend. Reparte SUS estados: no inventa fases de negocio. */
const GROUP_OF: Record<ProjectStatus, PortfolioGroup> = {
  DRAFT: "validation",
  VALIDATING: "validation",
  APPROVED: "execution",
  EXECUTING: "execution",
  MONITORING: "execution",
  PAUSED: "paused",
  COMPLETED: "closed",
  REJECTED: "closed",
  FAILED: "closed",
};

export type StatusTone = "ok" | "warn" | "bad" | "neutral";

export const PROJECT_STATUS_TONE: Record<ProjectStatus, StatusTone> = {
  DRAFT: "neutral",
  VALIDATING: "warn",
  APPROVED: "ok",
  EXECUTING: "ok",
  MONITORING: "ok",
  PAUSED: "neutral",
  COMPLETED: "ok",
  REJECTED: "bad",
  FAILED: "bad",
};

// --- La proyección (PLAN) ------------------------------------------------------------------------------------------

/** Qué lecturas de un proyecto fallaron. Un error de lectura **no es un dato**: no es «sin tareas», ni «sin decisión», ni
 * «sin fecha». Se dice que no se pudo leer. */
export type ReadName = "tasks" | "decision" | "audit";


/** Por qué un proyecto no tiene proyección. Nunca se sustituye por cero. */
export type PlanAbsence = "no_decision" | "decision_unread" | "no_finance_evidence" | "not_projected";

export const PLAN_ABSENCE_TEXT: Record<PlanAbsence, string> = {
  decision_unread: "No se pudo leer la decisión de este proyecto: no se sabe si tiene proyección.",
  no_decision: "El proyecto todavía no tiene decisión del Director ejecutivo: no hay ninguna proyección que leer.",
  no_finance_evidence: "La decisión no trae la evidencia de validación financiera: nadie proyectó este proyecto.",
  not_projected:
    "El especialista de finanzas no proyectó un beneficio mensual porque el objetivo no declaraba coste unitario o precio de venta.",
};

export const PLAN_NOTE =
  "Proyección sobre los supuestos que declaró el objetivo, calculada por el especialista de finanzas del Director " +
  "ejecutivo: no ha ocurrido y no es contabilidad. No incluye impuestos, IVA/OSS, caja, comisiones de pasarela ni " +
  "conversión de divisas. La evidencia financiera no declara moneda, así que la cifra se enseña sin símbolo y no se " +
  "suma con ninguna otra.";

/** Importe de una proyección, SIN símbolo de moneda: la evidencia no declara ninguna y poner «€» sería asumirla. */
export function formatPlanAmount(value: number): string {
  return value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Margen de una proyección (0–1) en porcentaje. */
export function formatPlanMargin(value: number): string {
  return value.toLocaleString("es-ES", { style: "percent", maximumFractionDigits: 1 });
}

// --- Lo que esta pantalla no calcula ------------------------------------------------------------------------------

/** Dicho una vez y en pantalla, para que ninguna ausencia parezca un descuido. */
export const NOT_CALCULATED: { label: string; reason: string }[] = [
  {
    label: "Beneficio, ingresos y ventas por proyecto",
    reason:
      "El registro de ingresos verificados (ADR 0030) guarda hechos de pago de un pedido, y un pedido puede llevar " +
      "varios productos. Imputar ese ingreso a un proyecto exigiría repartirlo, y no hay ninguna regla aprobada para " +
      "hacerlo: repartirlo por precio, por coste o por unidades sería inventarlo.",
  },
  {
    label: "Capital expuesto y límite de capital",
    reason:
      "Nadie registra cuánto capital tiene comprometido un proyecto. Antes salía de pedidos generados y de una constante.",
  },
  {
    label: "Margen de contribución por proyecto",
    reason: "El coste declarado vive en las líneas de pedido (Finanzas), y ninguna línea apunta a un proyecto.",
  },
  {
    label: "Mercado y categoría del proyecto",
    reason: "Un proyecto del backend no declara mercado ni categoría. Antes se escribían «eu» y «—» en el código.",
  },
  {
    label: "Fecha de inicio sin auditoría",
    reason:
      "La API de proyectos no expone `created_at`. Si la auditoría no registró el alta, la fecha es «Sin datos», nunca una fecha calculada.",
  },
  {
    label: "Documentos del proyecto",
    reason: "No hay gestor documental. La lista que había antes era de demostración.",
  },
];

// --- La tarjeta de un proyecto -------------------------------------------------------------------------------------

export interface ProjectMilestone {
  /** Nombre de la tarea en el grafo del Director ejecutivo. */
  task: string;
  label: string;
  state: PipelineStep["state"];
  /** Momento en que la auditoría registró `task.completed`; `null` = no registrado. */
  at: number | null;
}

export interface ProjectCard {
  id: string;
  name: string;
  status: ProjectStatus;
  statusLabel: string;
  statusTone: StatusTone;
  group: PortfolioGroup;
  /** Las cuatro etapas que el Director ejecutivo puede evidenciar, con el estado real de su tarea. */
  stages: PipelineStep[];
  progress: TaskProgress;
  decisionStatus: DecisionStatus | null;
  decisionLabel: string | null;
  rationale: string | null;
  /** Confianza de la decisión (0–1). `null` cuando no hay decisión: no es cero. */
  confidence: number | null;
  /** `null` cuando el backend no lo da: no es cero. */
  opportunityScore: number | null;
  plannedMonthlyProfit: Planned<number> | null;
  plannedMargin: Planned<number> | null;
  /** Por qué no hay proyección, cuando no la hay. */
  planAbsence: PlanAbsence | null;
  /** Las lecturas de este proyecto que fallaron. Vacío = todas bien. */
  unread: ReadName[];
  /** Momento del `project.created` de la auditoría; `null` = no registrado. */
  startedAt: number | null;
  milestones: ProjectMilestone[];
  /** Riesgos que los especialistas dejaron en la evidencia de la decisión. Sin nivel: nadie lo gradúa. */
  risks: ProjectRisk[];
}

export interface ProjectSource {
  project: Project;
  tasks: Task[];
  decision: Decision | null;
  /** Auditoría de la ejecución de este proyecto (la de su correlación). */
  audit: AuditEntry[];
  /** Lo que no se pudo leer: `tasks`, `decision` o `audit` están vacíos **porque falló la lectura**, no porque no existan. */
  unread?: ReadName[];
}

/** La primera vez que la auditoría registró una acción con esta forma exacta. `null` si no hay ninguna. */
function firstAuditAt(audit: AuditEntry[], action: string, resource: string): number | null {
  const times = audit
    .filter((entry) => entry.action === action && entry.resource === resource)
    .map((entry) => Date.parse(entry.created_at))
    .filter((time) => Number.isFinite(time));
  return times.length > 0 ? Math.min(...times) : null;
}

/** Un proyecto real del backend, con cada campo en su procedencia y sin ningún hueco relleno. */
export function projectCard({ project, tasks, decision, audit, unread = [] }: ProjectSource): ProjectCard {
  const stages = pipelineSteps(tasks, decision);
  const finance = projectedFinance(decision);

  const planAbsence: PlanAbsence | null =
    decision === null
      ? unread.includes("decision")
        ? "decision_unread"
        : "no_decision"
      : !decision.evidence.some((evidence) => evidence.source === "finance_validation")
        ? "no_finance_evidence"
        : finance === null
          ? "not_projected"
          : null;

  const milestones: ProjectMilestone[] = stages.map((stage) => {
    const task = tasks.find((candidate) => candidate.name === stage.task);
    return {
      task: stage.task,
      label: stage.label,
      state: stage.state,
      at: task ? firstAuditAt(audit, "task.completed", `task:${task.id}`) : null,
    };
  });

  return {
    id: project.id,
    name: project.name,
    status: project.status,
    statusLabel: PROJECT_STATUS_LABEL[project.status] ?? project.status,
    statusTone: PROJECT_STATUS_TONE[project.status] ?? "neutral",
    group: GROUP_OF[project.status] ?? "validation",
    stages,
    progress: taskProgress(tasks),
    decisionStatus: decision?.status ?? null,
    decisionLabel: decision ? DECISION_VERDICT[decision.status].title : null,
    rationale: decision?.rationale ?? null,
    confidence: decision?.confidence ?? null,
    opportunityScore: decision?.opportunity_score ?? null,
    plannedMonthlyProfit: finance === null ? null : planned(finance.monthlyProfit),
    plannedMargin: finance === null || finance.margin === null ? null : planned(finance.margin),
    planAbsence,
    unread: [...unread],
    startedAt: firstAuditAt(audit, "project.created", `project:${project.id}`),
    milestones,
    risks: risksFromDecision(decision),
  };
}

// --- La cartera ----------------------------------------------------------------------------------------------------

export interface PortfolioCounts {
  total: number;
  validation: number;
  execution: number;
  paused: number;
  closed: number;
  /** Cuántos proyectos traen proyección. No se SUMAN: la evidencia financiera no declara moneda. */
  withPlan: number;
}

export function portfolioCounts(projects: ProjectCard[]): PortfolioCounts {
  const of = (group: PortfolioGroup) => projects.filter((project) => project.group === group).length;
  return {
    total: projects.length,
    validation: of("validation"),
    execution: of("execution"),
    paused: of("paused"),
    closed: of("closed"),
    withPlan: projects.filter((project) => project.plannedMonthlyProfit !== null).length,
  };
}

export type PortfolioTab = "all" | PortfolioGroup;

export const PORTFOLIO_TABS: { key: PortfolioTab; label: string }[] = [
  { key: "all", label: "Todos" },
  { key: "validation", label: "En validación" },
  { key: "execution", label: "En ejecución" },
  { key: "paused", label: "Pausados" },
  { key: "closed", label: "Cerrados" },
];

export function filterProjects(
  projects: ProjectCard[],
  filters: { tab: PortfolioTab; query?: string; status?: string },
): ProjectCard[] {
  const query = (filters.query ?? "").trim().toLowerCase();
  return projects.filter((project) => {
    if (filters.tab !== "all" && project.group !== filters.tab) return false;
    if (query && !`${project.id} ${project.name}`.toLowerCase().includes(query)) return false;
    if (filters.status && filters.status !== "all" && project.status !== filters.status) return false;
    return true;
  });
}

/** Reparto de la cartera por bloque de estados del backend. */
export function statusDistribution(
  projects: ProjectCard[],
): { key: PortfolioGroup; label: string; value: number; color: string }[] {
  const counts = portfolioCounts(projects);
  return [
    { key: "validation", label: "En validación", value: counts.validation, color: "#e056c8" },
    { key: "execution", label: "En ejecución", value: counts.execution, color: "#4f8df7" },
    { key: "paused", label: "Pausados", value: counts.paused, color: "#7a8b99" },
    { key: "closed", label: "Cerrados", value: counts.closed, color: "#00d69a" },
  ];
}

// --- Detalle -------------------------------------------------------------------------------------------------------

export interface NextStep {
  /** La etapa que el proyecto tiene delante; `null` cuando el grafo no deja ninguna abierta. */
  stage: PipelineStep | null;
  title: string;
  href: string | null;
  /** El veredicto de la decisión del Director ejecutivo, si la hay. */
  decision: string | null;
}

const STEP_TITLE: Record<string, string> = {
  product_validation: "Validar la oportunidad",
  supplier_sourcing: "Elegir proveedor",
  finance_validation: "Validar la economía",
  legal_validation: "Cerrar el Legal Gate",
};

/** Lo siguiente que le toca al proyecto: la primera etapa de su grafo que no está cerrada. */
export function nextStep(project: ProjectCard): NextStep {
  const stage = project.stages.find((candidate) => candidate.state !== "done") ?? null;
  return {
    stage,
    title: stage ? (STEP_TITLE[stage.task] ?? stage.label) : "Todas las etapas del grafo están completadas",
    href: stage?.href ?? null,
    decision: project.decisionLabel,
  };
}

/** Una fecha o una cifra ausente se dice con el mismo vocabulario que Finanzas y el Panel. */
export { NO_DATA, UNREAD };
