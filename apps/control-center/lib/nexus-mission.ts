import type { Agent, Approval, Decision, Project, Task } from "./api.ts";
import { approvalsContract } from "./ceo-block-contracts.ts";
import { parseUtc } from "./dates.ts";
import { DOMAINS, domainOfRole, type DomainKey } from "./nexus-domains.ts";
import { readList, type ReadState } from "./read-state.ts";

// LA ÚLTIMA MISIÓN REGISTRADA del Director ejecutivo y sus tareas (M47, Commit 4). Capa pura de datos: contratos de lectura, criterio de
// «última», progreso y dependencias reales. No hay nada de demostración ni se escribe en el backend.
//
// CRITERIO DE «ÚLTIMA MISIÓN» (verificado en el backend, sin metadatos inventados):
//   · El ÚNICO sitio que crea un `Project` es `CEOOrchestrator.run_objective`, y solo se invoca desde `POST /api/objectives/{id}/run`.
//   · En esa misma ejecución, y en la misma transacción, se crean las tareas del proyecto y su decisión (`_synthesize_decision` hace el
//     `flush` antes de cualquier commit intermedio): un proyecto confirmado tiene una decisión (en Supabase: 1 proyecto, 1 decisión, 5 tareas).
//   · Un objetivo sin ejecutar no tiene proyecto; una ejecución que falla antes del commit no deja proyecto.
//   · La API no dice QUIÉN lanzó la misión (el botón, un script o un cliente de la API): por eso se llama «última misión registrada», no «la
//     que lanzó este botón».
// Por tanto la última misión es el proyecto más reciente por `created_at` (con desempate por id, y sin fiarse del orden de la API).

/** Los estados que el backend envía para una tarea (`TaskStatus` de `tasks/schemas.py`). `BLOCKED` NO existe en el backend. */
export const TASK_STATUSES = ["PENDING", "QUEUED", "RUNNING", "WAITING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED", "BLOCKED"] as const;
const DECISION_STATUSES = ["GO", "REVIEW", "NO_GO", "HUMAN_APPROVAL"] as const;

/** Cómo se llama cada estado de tarea (los del backend). */
export const TASK_STATUS_TEXT = {
  PENDING: "Pendiente",
  QUEUED: "En cola",
  RUNNING: "En ejecución",
  WAITING: "En espera",
  WAITING_APPROVAL: "Esperando aprobación",
  COMPLETED: "Completada",
  FAILED: "Fallida",
  CANCELLED: "Cancelada",
  BLOCKED: "Bloqueada",
} as const;

export const taskStatusText = (status: string): string => TASK_STATUS_TEXT[status as keyof typeof TASK_STATUS_TEXT] ?? status;
export const isFailedTask = (item: Pick<Task, "status">): boolean => item.status === "FAILED";

// --- Contratos ----------------------------------------------------------------------------------------------------------------

const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const isOneOf = <T extends string>(options: readonly T[], value: unknown): value is T => typeof value === "string" && (options as readonly string[]).includes(value);
type Row = Record<string, unknown>;

function contract<T>(state: ReadState<T[]>, subject: string, check: (row: Row) => string | null): ReadState<T[]> {
  if (state.kind !== "loaded") return state;
  for (const [index, row] of state.data.entries()) {
    const reason = row !== null && typeof row === "object" ? check(row as Row) : "no es un objeto";
    if (reason !== null) return { kind: "error", message: `${subject} no tienen el formato que esta pantalla espera (fila ${index + 1}: ${reason}).` };
  }
  return state;
}

export const projectsContract = (state: ReadState<Project[]>): ReadState<Project[]> =>
  contract(state, "Las misiones", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.name)) return "sin nombre";
    if (typeof row.created_at !== "string" || Number.isNaN(parseUtc(row.created_at))) return "fecha de creación ilegible";
    return null;
  });

export const decisionsContract = (state: ReadState<Decision[]>): ReadState<Decision[]> =>
  contract(state, "Las decisiones", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isOneOf(DECISION_STATUSES, row.status)) return `estado desconocido (${JSON.stringify(row.status)})`;
    if (!Array.isArray(row.evidence) || !row.evidence.every((item) => item !== null && typeof item === "object" && typeof (item as Row).source === "string")) {
      return "evidencias que no son una lista";
    }
    return null;
  });

export const tasksContract = (state: ReadState<Task[]>): ReadState<Task[]> =>
  contract(state, "Las tareas", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.capability)) return "sin capacidad";
    if (!isOneOf(TASK_STATUSES, row.status)) return `estado desconocido (${JSON.stringify(row.status)})`;
    if (!Array.isArray(row.depends_on) || !row.depends_on.every((id) => typeof id === "string")) return "`depends_on` que no es una lista de ids";
    return null;
  });

// --- Criterio de «última» -----------------------------------------------------------------------------------------------------

/** El proyecto más reciente por `created_at`; con la misma fecha, el id mayor. No depende del orden en que llegue la lista. */
export function latestProject(projects: Project[]): Project | null {
  let best: Project | null = null;
  for (const candidate of projects) {
    if (best === null) {
      best = candidate;
      continue;
    }
    const a = parseUtc(candidate.created_at);
    const b = parseUtc(best.created_at);
    if (a > b || (a === b && candidate.id > best.id)) best = candidate;
  }
  return best;
}

// --- Progreso (D-4-2) ---------------------------------------------------------------------------------------------------------

export interface TaskProgress {
  /** Tareas relevantes: todas salvo las CANCELLED. */
  total: number;
  /** Solo las COMPLETED. FAILED y WAITING_APPROVAL NO cuentan como completadas. */
  completed: number;
  fraction: number;
}

/** COMPLETED / tareas no CANCELLED. Sin tareas relevantes no hay progreso (`null`): nunca un 0 %. */
export function taskProgress(tasks: Task[]): TaskProgress | null {
  const relevant = tasks.filter((item) => item.status !== "CANCELLED");
  if (relevant.length === 0) return null;
  const completed = relevant.filter((item) => item.status === "COMPLETED").length;
  return { total: relevant.length, completed, fraction: completed / relevant.length };
}

// --- Dependencias reales (D-4-4) ----------------------------------------------------------------------------------------------

export interface DomainDependency {
  source: DomainKey;
  target: DomainKey;
}

/** Las dependencias de `depends_on` de tareas reales, llevadas a los dominios de sus capacidades. Una capacidad solo se lleva a un dominio si
 * TODOS los agentes que la tienen son del mismo dominio; una capacidad sin agente (`decision_synthesis`), ambigua, un padre inexistente o
 * dos tareas del mismo dominio no dibujan nada. Sin `depends_on` no hay aristas: no se crean líneas por similitud de dominio o de capacidad. */
export function taskDependencyEdges(tasks: Task[], agents: Agent[]): DomainDependency[] {
  const domainsOfCapability = new Map<string, Set<DomainKey>>();
  for (const agent of agents) {
    const domain = domainOfRole(agent.role);
    for (const capability of agent.capabilities) domainsOfCapability.set(capability, (domainsOfCapability.get(capability) ?? new Set<DomainKey>()).add(domain));
  }
  const domainOf = (capability: string): DomainKey | null => {
    const domains = domainsOfCapability.get(capability);
    return domains !== undefined && domains.size === 1 ? [...domains][0] : null;
  };
  const byId = new Map(tasks.map((item) => [item.id, item] as const));
  const pairs = new Map<string, DomainDependency>();
  for (const child of tasks) {
    const target = domainOf(child.capability);
    if (target === null) continue;
    for (const parentId of child.depends_on ?? []) {
      const parent = byId.get(parentId);
      const source = parent === undefined ? null : domainOf(parent.capability);
      if (source === null || source === target) continue;
      pairs.set(`${source}→${target}`, { source, target });
    }
  }
  return [...pairs.values()].sort((a, b) => DOMAINS.indexOf(a.source) - DOMAINS.indexOf(b.source) || DOMAINS.indexOf(a.target) - DOMAINS.indexOf(b.target));
}

// --- Lectura de la cadena proyecto → decisión + tareas -------------------------------------------------------------------------

/** Lo que el grafo necesita del cliente de la API para leer la última misión. */
export interface MissionSource {
  listProjects(): Promise<Project[]>;
  listDecisionsForProject(projectId: string): Promise<Decision[]>;
  listTasks(projectId: string): Promise<Task[]>;
  /** Las aprobaciones: de ellas sale el ESTADO de aprobación de la decisión (la decisión `HUMAN_APPROVAL` es una clasificación del motor). */
  listApprovals(): Promise<Approval[]>;
}

export interface MissionRead {
  projects: ReadState<Project[]>;
  /** La última misión, si la lectura de proyectos fue válida y no estaba vacía. */
  project: Project | null;
  /** La decisión de ESA misión: `loaded` con una, `empty` si no tiene (un hecho), `error` si falló o si hay más de una. */
  decision: ReadState<Decision>;
  tasks: ReadState<Task[]>;
  /** La aprobación de ESA decisión (`approvals.decision_id`): `loaded` con una, `empty` si no tiene (o si la decisión no la pide), `error` si
   * falló o si hay más de una. Es el ESTADO de la aprobación; el estado de la decisión (`HUMAN_APPROVAL`) es otra cosa y no cambia al resolverla. */
  approval: ReadState<Approval>;
}

const NOT_READ = "No se leyó: antes hace falta la lista de misiones.";

/** Lee los proyectos y, del ÚLTIMO, su decisión y sus tareas (una petición cada una). Un fallo de proyectos no se convierte en «sin
 * misiones»; un fallo de la decisión o de las tareas rompe solo esa parte. */
export async function readMission(source: MissionSource): Promise<MissionRead> {
  const projects = projectsContract(await readList(() => source.listProjects(), "las misiones"));
  const project = projects.kind === "loaded" ? latestProject(projects.data) : null;
  if (project === null) {
    return {
      projects,
      project: null,
      decision: { kind: "unread", reason: NOT_READ },
      tasks: { kind: "unread", reason: NOT_READ },
      approval: { kind: "unread", reason: NOT_READ },
    };
  }
  const [decisions, tasks, approvals] = await Promise.all([
    readList(() => source.listDecisionsForProject(project.id), "la decisión de la última misión"),
    readList(() => source.listTasks(project.id), "las tareas de la última misión"),
    readList(() => source.listApprovals(), "las aprobaciones"),
  ]);
  const checked = decisionsContract(decisions);
  const decision: ReadState<Decision> =
    checked.kind === "loaded"
      ? checked.data.length === 1
        ? { kind: "loaded", data: checked.data[0] }
        : { kind: "error", message: "La última misión tiene más de una decisión: no se sabe cuál enseñar." }
      : checked.kind === "empty"
        ? { kind: "empty" }
        : checked;
  return { projects, project, decision, tasks: tasksContract(tasks), approval: approvalOfDecision(decision, approvalsContract(approvals)) };
}

/** La aprobación de la decisión: solo existe para una decisión que la pide. Un fallo de lectura es `error`, nunca «sin aprobación». */
export function approvalOfDecision(decision: ReadState<Decision>, approvals: ReadState<Approval[]>): ReadState<Approval> {
  if (decision.kind !== "loaded") return { kind: "unread", reason: "No se leyó: antes hace falta la decisión." };
  if (decision.data.status !== "HUMAN_APPROVAL") return { kind: "empty" };
  if (approvals.kind === "error" || approvals.kind === "unread") return approvals;
  const mine = approvals.kind === "loaded" ? approvals.data.filter((item) => item.decision_id === decision.data.id) : [];
  if (mine.length === 0) return { kind: "empty" };
  if (mine.length > 1) return { kind: "error", message: "La decisión tiene más de una aprobación: no se sabe cuál enseñar." };
  return { kind: "loaded", data: mine[0] };
}
