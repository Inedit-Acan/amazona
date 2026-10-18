import type { Approval, Incident, PipelineKillSwitchState, PipelineReview, Product } from "./api.ts";
import { parseUtc } from "./dates.ts";
import type { ReadState } from "./read-state.ts";

// El CONTRATO de cada lectura de los bloques ejecutivos (M47, Commit 3B). `readList` solo comprueba que la respuesta es una lista; aquí
// se comprueba cada fila. Una fila que no cumple el contrato rompe la lectura entera: es `error` (visible y con un texto nuestro),
// nunca una lista vacía, una fila ignorada en silencio, una fila sin insignia ni un valor por defecto («Media»).
//
// Un valor fuera del vocabulario cerrado significa que el backend y la pantalla ya no se entienden. Quien lo ve es el usuario, en el
// bloque afectado, no un `console.warn`.

const APPROVAL_STATUSES = ["PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"] as const;
const BUDGET_EFFECTS = ["none", "reserved", "committed", "released"] as const;
const REVIEW_KINDS = ["POST_HOC", "ACTION_GATE"] as const;
const REVIEW_STATUSES = ["PENDING", "APPROVED", "REJECTED", "CONSUMED"] as const;
const PRODUCT_STATUSES = ["CANDIDATE"] as const;
const PRODUCT_SOURCES = ["research", "manual"] as const;
const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
const INCIDENT_STATUSES = ["OPEN", "RESOLVED"] as const;

const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const isOneOf = <T extends string>(options: readonly T[], value: unknown): value is T => typeof value === "string" && (options as readonly string[]).includes(value);
const isInstant = (value: unknown): value is string => typeof value === "string" && !Number.isNaN(parseUtc(value));
const isNullableInstant = (value: unknown) => value === null || isInstant(value);
const isNullableText = (value: unknown) => value === null || typeof value === "string";

type Row = Record<string, unknown>;

/** La primera razón por la que una fila no cumple el contrato, o `null` si lo cumple. */
type Check = (row: Row) => string | null;

function brokenMessage(subject: string, index: number, reason: string): string {
  return `${subject} no tienen el formato que esta pantalla espera (fila ${index + 1}: ${reason}).`;
}

function contract<T>(state: ReadState<T[]>, subject: string, check: Check): ReadState<T[]> {
  if (state.kind !== "loaded") return state;
  for (const [index, row] of state.data.entries()) {
    const reason = row !== null && typeof row === "object" ? check(row as Row) : "no es un objeto";
    if (reason !== null) return { kind: "error", message: brokenMessage(subject, index, reason) };
  }
  return state;
}

export const approvalsContract = (state: ReadState<Approval[]>): ReadState<Approval[]> =>
  contract(state, "Las aprobaciones", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.action)) return "sin acción";
    if (!isOneOf(APPROVAL_STATUSES, row.status)) return `estado desconocido (${JSON.stringify(row.status)})`;
    if (!(row.amount === null || (typeof row.amount === "number" && Number.isFinite(row.amount)))) return "importe que no es un número";
    if (!isNullableInstant(row.expires_at)) return "vencimiento que no es una fecha";
    // Commit 6b: los dos campos son opcionales (un backend anterior al 6a no los envía) pero, si llegan, tienen que ser válidos.
    if ("requested_at" in row && !isInstant(row.requested_at)) return "fecha de solicitud que no es una fecha";
    if ("correlation_id" in row && !isText(row.correlation_id)) return "correlación que no es texto";
    // Corrección tras la primera misión real: el efecto en el libro del presupuesto, opcional (backend anterior) pero válido si llega.
    if ("budget_effect" in row && !isOneOf(BUDGET_EFFECTS, row.budget_effect)) return `efecto en el presupuesto desconocido (${JSON.stringify(row.budget_effect)})`;
    return null;
  });

export const reviewsContract = (state: ReadState<PipelineReview[]>): ReadState<PipelineReview[]> =>
  contract(state, "Las revisiones de pipeline", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isOneOf(REVIEW_KINDS, row.kind)) return `tipo desconocido (${JSON.stringify(row.kind)})`;
    if (!isOneOf(REVIEW_STATUSES, row.status)) return `estado desconocido (${JSON.stringify(row.status)})`;
    if (!isNullableText(row.step) || !isNullableText(row.action)) return "paso o acción que no son texto";
    if (!Array.isArray(row.reasons) || !row.reasons.every((reason) => typeof reason === "string")) return "motivos que no son una lista de textos";
    return null;
  });

export const productsContract = (state: ReadState<Product[]>): ReadState<Product[]> =>
  contract(state, "Los productos del catálogo", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.name)) return "sin nombre";
    if (typeof row.category !== "string") return "categoría que no es texto";
    if (!isOneOf(PRODUCT_STATUSES, row.status)) return `estado que no es de candidato (${JSON.stringify(row.status)})`;
    if (!isOneOf(PRODUCT_SOURCES, row.source)) return `origen desconocido (${JSON.stringify(row.source)})`;
    return null;
  });

export const incidentsContract = (state: ReadState<Incident[]>): ReadState<Incident[]> =>
  contract(state, "Las incidencias", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.title)) return "sin título";
    if (!isOneOf(SEVERITIES, row.severity)) return `severidad desconocida (${JSON.stringify(row.severity) ?? "ausente"})`;
    if (!isOneOf(INCIDENT_STATUSES, row.status)) return `estado desconocido (${JSON.stringify(row.status)})`;
    if (!isInstant(row.created_at)) return "fecha de apertura que no es una fecha";
    if (!isNullableText(row.description)) return "descripción que no es texto";
    return null;
  });

export function killSwitchContract(state: ReadState<PipelineKillSwitchState>): ReadState<PipelineKillSwitchState> {
  if (state.kind !== "loaded") return state;
  const data = state.data as unknown as Row | null;
  const reason = data === null || typeof data !== "object" ? "no es un objeto" : typeof data.enabled !== "boolean" ? "`enabled` no es un booleano" : !isNullableText(data.reason) ? "motivo que no es texto" : null;
  return reason === null ? state : { kind: "error", message: `El estado del pipeline no tiene el formato que esta pantalla espera (${reason}).` };
}
