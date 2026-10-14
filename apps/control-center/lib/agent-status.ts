// El estado de un agente TAL COMO LO DICE EL BACKEND (M47, Commit 1).
//
// `AgentStatus` es el vocabulario del registro de agentes (`backend/app/agents/base.py`, `class AgentStatus`): siete
// valores y ninguno más. No existe `OFFLINE`, ni `ERROR`, ni `ONLINE`. Antes, el grafo y tres pantallas traducían ese
// texto con una tabla que incluía `OFFLINE` y `ERROR` (que el backend nunca envía) y caía en «disponible» ante cualquier
// otro valor: un agente `FAILED`, `DISABLED`, `BLOCKED` o `DEGRADED` se pintaba como «Disponible».
//
// Este módulo NO es `ReadState`. `AgentStatus` es un DATO que el backend devolvió; `ReadState` (lib/read-state.ts) dice
// si se pudo LEER ese dato. Si el registro no se pudo leer no existe ningún estado de agente: no se inventa uno
// («no disponible», «desconocido», «offline»…), se queda el `ReadState` en `error`/`unread`. Y si el backend envía un
// texto que este código no conoce, eso es `unknown` (se enseña tal cual), nunca un estado conocido por defecto.

/** Los estados del registro de agentes. Un test (`lib/agent-status.test.ts`) lee el `StrEnum` del backend y exige que
 * esta lista coincida con él: si el backend añade o quita uno, el CI falla. */
export const AGENT_STATUSES = ["AVAILABLE", "BUSY", "WAITING", "BLOCKED", "DEGRADED", "DISABLED", "FAILED"] as const;

export type AgentStatus = (typeof AGENT_STATUSES)[number];

/** Lo que dice el registro: un estado conocido, o un texto que este código no reconoce (se conserva tal cual). */
export type AgentStatusReading = { kind: "known"; status: AgentStatus } | { kind: "unknown"; raw: string };

const KNOWN: ReadonlySet<string> = new Set(AGENT_STATUSES);

/** Clasifica el texto que devuelve el backend. Distingue mayúsculas: el contrato es exacto, y `"available"` o
 * `"OFFLINE"` no son estados del registro. */
export function readAgentStatus(raw: string): AgentStatusReading {
  return KNOWN.has(raw) ? { kind: "known", status: raw as AgentStatus } : { kind: "unknown", raw };
}

/** Cómo se le llama a cada estado en la interfaz. Sin eufemismos: `FAILED` es «Fallido», no «Error» ni «Inactivo». */
export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
  AVAILABLE: "Disponible",
  BUSY: "Ocupado",
  WAITING: "Esperando",
  BLOCKED: "Bloqueado",
  DEGRADED: "Degradado",
  DISABLED: "Deshabilitado",
  FAILED: "Fallido",
};

/** El estado del registro dicho para una persona; un texto desconocido se enseña entre comillas y se dice que lo es. */
export function agentStatusText(reading: AgentStatusReading): string {
  return reading.kind === "known" ? AGENT_STATUS_LABEL[reading.status] : `Desconocido («${reading.raw}»)`;
}

/** El agente puede aceptar trabajo ahora mismo según el registro. Solo estos tres estados lo dicen; `BLOCKED`,
 * `DEGRADED`, `DISABLED`, `FAILED` y todo lo desconocido NO cuentan como operativos. */
export function isOperational(reading: AgentStatusReading): boolean {
  return reading.kind === "known" && (reading.status === "AVAILABLE" || reading.status === "BUSY" || reading.status === "WAITING");
}
