import type { Agent, AgentExecution, AuditEntry } from "./api.ts";
import { parseUtc } from "./dates.ts";
import type { ReadState } from "./read-state.ts";

// El CONTRATO de cada lectura de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5). `readList` solo comprueba que la
// respuesta es una lista; aquí se comprueba cada fila. Una fila que no cumple rompe la lectura entera: es `error` (visible y con un
// texto nuestro), nunca una lista vacía, una fila ignorada en silencio ni un valor por defecto.
//
// Una fecha que no se interpreta rompería el orden de «lo último», que es lo único que dice la actividad: por eso es un contrato roto.

const isText = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const isInstant = (value: unknown): value is string => typeof value === "string" && !Number.isNaN(parseUtc(value));
const isDuration = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;

type Row = Record<string, unknown>;
type Check = (row: Row) => string | null;

function contract<T>(state: ReadState<T[]>, subject: string, check: Check): ReadState<T[]> {
  if (state.kind !== "loaded") return state;
  for (const [index, row] of state.data.entries()) {
    const reason = row !== null && typeof row === "object" ? check(row as Row) : "no es un objeto";
    if (reason !== null) return { kind: "error", message: `${subject} no tienen el formato que esta pantalla espera (fila ${index + 1}: ${reason}).` };
  }
  return state;
}

export const auditContract = (state: ReadState<AuditEntry[]>): ReadState<AuditEntry[]> =>
  contract(state, "Las entradas de auditoría", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.actor)) return "sin actor";
    if (!isText(row.action)) return "sin acción";
    if (typeof row.resource !== "string") return "recurso que no es texto";
    if (!isInstant(row.created_at)) return "fecha que no es una fecha";
    return null;
  });

export const executionsContract = (state: ReadState<AgentExecution[]>): ReadState<AgentExecution[]> =>
  contract(state, "Las ejecuciones de los agentes", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.agent_id)) return "sin agente";
    if (typeof row.capability !== "string") return "capacidad que no es texto";
    if (!isDuration(row.duration_ms)) return "duración que no es un número válido";
    if (typeof row.success !== "boolean") return "resultado que no es un booleano";
    if (!isInstant(row.created_at)) return "fecha que no es una fecha";
    return null;
  });

export const agentsContract = (state: ReadState<Agent[]>): ReadState<Agent[]> =>
  contract(state, "Los agentes", (row) => {
    if (!isText(row.id)) return "sin id";
    if (!isText(row.name)) return "sin nombre";
    if (!isText(row.role)) return "sin rol";
    return null;
  });
