
// El registro de auditoría es una lista de AuditLog: actor, acción, recurso, estado
// antes/después, ID de correlación y fecha. No tiene tipo, criticidad, resultado,
// proyecto, IP, hash ni evidencias. Aquí solo se deduce lo que la propia entrada
// permite (categoría por el prefijo de la acción, tipo de actor por su nombre y
// cambios de estado); la pantalla la construye lib/audit-view.ts.

export type EventCategory = "Proyecto" | "Decisión" | "Aprobación" | "Análisis" | "Pipeline" | "Memoria" | "Incidencia" | "Seguridad" | "Otros";

/** Categoría de una acción (`project.created`, `economics.run`…) según su prefijo. */
export function eventCategory(action: string): EventCategory {
  const prefix = action.split(".")[0];
  switch (prefix) {
    case "project":
    case "tasks":
    case "task":
      return "Proyecto";
    case "decision":
      return "Decisión";
    case "approval":
    case "pipeline_review":
      return "Aprobación";
    case "memory":
      return "Memoria";
    case "incident":
      return "Incidencia";
    case "kill_switch":
    case "killswitch":
    case "auth":
    case "permission":
      return "Seguridad";
    case "pipeline":
      return "Pipeline";
    default:
      return action.endsWith(".run") ? "Análisis" : "Otros";
  }
}

export type ActorKind = "Agente" | "Persona" | "Orquestador" | "Sistema";

/** Tipo de actor deducido del nombre: `agent-*`, un correo, el CEO o el sistema. */
export function actorKind(actor: string): ActorKind {
  if (actor.startsWith("agent-") || actor.endsWith("-orchestrator-1")) return "Agente";
  if (actor.includes("@")) return "Persona";
  if (actor === "ceo") return "Orquestador";
  return "Sistema";
}

/** La acción indica un fallo o error (`task.failed`, `…error`). */
export function isErrorAction(action: string): boolean {
  return /fail|error/i.test(action);
}

export interface StateChange {
  key: string;
  before: string | null;
  after: string | null;
}

function show(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Claves de `before`/`after` con su valor antes y después (null si no existía). */
export function stateChanges(before: Record<string, unknown> | null, after: Record<string, unknown> | null): StateChange[] {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].sort();
  return keys.map((key) => ({
    key,
    before: before && key in before ? show(before[key]) : null,
    after: after && key in after ? show(after[key]) : null,
  }));
}
