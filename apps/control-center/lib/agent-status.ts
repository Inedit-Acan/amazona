// El estado de un agente TAL COMO LO DICE EL BACKEND, y la ÚNICA tabla que lo presenta (M47, Commits 1 y 1b).
//
// CONTRATO. `AgentStatus` es el vocabulario del registro de agentes (`backend/app/agents/base.py`, `class AgentStatus`):
// siete valores y ninguno más. No existe `OFFLINE`, ni `ERROR`, ni `ONLINE`. Un test (`lib/agent-status.test.ts`) lee ese
// `StrEnum` y exige que `AGENT_STATUSES` y `AGENT_PRESENTATION` coincidan con él: si el backend añade o quita un estado, el CI
// falla en vez de que la interfaz lo pinte, en silencio, como «disponible».
//
// ESTA TABLA ES LA ÚNICA. Antes había una por pantalla (Agentes, Panel, Proyectos, el grafo) y dos comparaciones por
// literal (`status !== "OFFLINE"`), todas con estados inexistentes y con `?? "available"` para el resto. Agentes, Panel,
// Estado, Proyectos y el grafo leen de aquí; `lib/nexus-boundary.test.ts` y `lib/agent-status-boundary.test.ts` impiden que
// vuelva a nacer una copia.
//
// CLASIFICACIÓN DE LA INTERFAZ (no es un estado del backend). «Operativo», la severidad de la alerta y el tono son
// DERIVACIONES de presentación que decide esta interfaz; el backend no los envía y no los conoce:
//   · operativo      = AVAILABLE · BUSY · WAITING   (el registro no lo da por bloqueado, degradado, apagado ni averiado)
//   · no operativo   = BLOCKED · DEGRADED · DISABLED · FAILED
//   · desconocido    = cualquier otro texto: no es operativo ni no operativo, es un estado que esta interfaz no reconoce.
// Contrastado con el backend: «operativo» NO significa «recibirá trabajo». `AgentManager.select_agent` solo elige agentes
// `AVAILABLE`; `AgentRegistry.find_by_capability` descarta únicamente `DISABLED` y `FAILED`. Es decir, un agente `BUSY` o
// `WAITING` es «operativo» para esta interfaz pero el despachador no le asignará trabajo nuevo hasta que vuelva a
// `AVAILABLE`, y un `BLOCKED`/`DEGRADED` sigue visible para el registro aunque no se le asigne nada. No se usa «en línea»
// ni «online/offline»: el backend no mide conectividad.
//
// Este módulo NO es `ReadState` (lib/read-state.ts). `AgentStatus` es un DATO que el backend devolvió; `ReadState` dice si
// se pudo LEER ese dato. Si el registro no se pudo leer no existe ningún estado de agente: no se inventa uno, se queda el
// `ReadState` en `error`/`unread`. Y un texto que el backend envía y este código no conoce es `unknown`: se enseña tal cual
// («Desconocido»), nunca como un estado conocido por defecto, y NO es una alerta del agente.

/** Los estados del registro de agentes. */
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

// --- Presentación (la única tabla) ----------------------------------------------------------------------------------

/** La categoría con la que las pantallas hablan de un agente. Una por estado del registro, más `unknown`. */
export type AgentActivity = "available" | "running" | "waiting" | "blocked" | "degraded" | "disabled" | "failed" | "unknown";

/** Mismos valores que `LevelTone` (components/level-chip.tsx): `lib` no importa componentes. */
export type AgentTone = "ok" | "warn" | "bad" | "neutral";

export type AlertSeverity = "Alta" | "Media";

export interface AgentPresentation {
  activity: AgentActivity;
  /** Texto que se enseña. Siempre lo lleva: el color nunca va solo. */
  label: string;
  tone: AgentTone;
  /** Clasificación de la interfaz (ver arriba); no es un estado del backend. */
  operational: boolean;
  /** Severidad de la alerta que genera por sí mismo este estado; `null` = ninguna. */
  alert: AlertSeverity | null;
}

/** AVAILABLE verde; BUSY verde activo (se distingue por icono y borde en el chip); WAITING ámbar suave (espera legítima);
 * DEGRADED ámbar; BLOCKED y FAILED rojo; DISABLED gris (se apagó, no se rompió: no es alerta). */
export const AGENT_PRESENTATION: Record<AgentStatus, AgentPresentation> = {
  AVAILABLE: { activity: "available", label: "Disponible", tone: "ok", operational: true, alert: null },
  BUSY: { activity: "running", label: "Ejecutando", tone: "ok", operational: true, alert: null },
  WAITING: { activity: "waiting", label: "En espera", tone: "warn", operational: true, alert: null },
  BLOCKED: { activity: "blocked", label: "Bloqueado", tone: "bad", operational: false, alert: "Alta" },
  DEGRADED: { activity: "degraded", label: "Degradado", tone: "warn", operational: false, alert: "Media" },
  DISABLED: { activity: "disabled", label: "Deshabilitado", tone: "neutral", operational: false, alert: null },
  FAILED: { activity: "failed", label: "Fallido", tone: "bad", operational: false, alert: "Alta" },
};

/** Un texto que el registro envió y esta interfaz no reconoce. No es operativo, no es no operativo y no es una alerta. */
export const UNKNOWN_PRESENTATION: AgentPresentation = {
  activity: "unknown",
  label: "Desconocido",
  tone: "neutral",
  operational: false,
  alert: null,
};

export function presentAgentStatus(reading: AgentStatusReading): AgentPresentation {
  return reading.kind === "known" ? AGENT_PRESENTATION[reading.status] : UNKNOWN_PRESENTATION;
}

/** La categoría de un estado tal como llega del backend. */
export function activityOfStatus(raw: string): AgentActivity {
  return presentAgentStatus(readAgentStatus(raw)).activity;
}

const BY_ACTIVITY: Record<AgentActivity, AgentPresentation> = {
  available: AGENT_PRESENTATION.AVAILABLE,
  running: AGENT_PRESENTATION.BUSY,
  waiting: AGENT_PRESENTATION.WAITING,
  blocked: AGENT_PRESENTATION.BLOCKED,
  degraded: AGENT_PRESENTATION.DEGRADED,
  disabled: AGENT_PRESENTATION.DISABLED,
  failed: AGENT_PRESENTATION.FAILED,
  unknown: UNKNOWN_PRESENTATION,
};

/** La presentación de una categoría (etiqueta, tono…). No es una tabla nueva: es la misma, indexada por categoría. */
export function presentActivity(activity: AgentActivity): AgentPresentation {
  return BY_ACTIVITY[activity];
}

/** Etiqueta de cada estado del registro. Derivada de `AGENT_PRESENTATION`. */
export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = Object.fromEntries(
  AGENT_STATUSES.map((status) => [status, AGENT_PRESENTATION[status].label]),
) as Record<AgentStatus, string>;

/** El estado del registro dicho para una persona; un texto desconocido se enseña entre comillas y se dice que lo es. */
export function agentStatusText(reading: AgentStatusReading): string {
  return reading.kind === "known" ? AGENT_PRESENTATION[reading.status].label : `Desconocido («${reading.raw}»)`;
}

/** Operativo según la clasificación de la interfaz (ver arriba). */
export function isOperational(reading: AgentStatusReading): boolean {
  return presentAgentStatus(reading).operational;
}

// --- Recuentos ---------------------------------------------------------------------------------------------------------

export interface AgentStatusSummary {
  total: number;
  /** AVAILABLE + BUSY + WAITING. */
  operational: number;
  /** BLOCKED + DEGRADED + DISABLED + FAILED. */
  notOperational: number;
  /** Estados que esta interfaz no reconoce: no cuentan ni como operativos ni como no operativos. */
  unknown: number;
  byStatus: Record<AgentStatus, number>;
}

/** Siempre `operational + notOperational + unknown === total`. */
export function summarizeAgentStatuses(statuses: readonly string[]): AgentStatusSummary {
  const byStatus = Object.fromEntries(AGENT_STATUSES.map((status) => [status, 0])) as Record<AgentStatus, number>;
  let operational = 0;
  let notOperational = 0;
  let unknown = 0;
  for (const raw of statuses) {
    const reading = readAgentStatus(raw);
    if (reading.kind === "unknown") {
      unknown += 1;
      continue;
    }
    byStatus[reading.status] += 1;
    if (AGENT_PRESENTATION[reading.status].operational) operational += 1;
    else notOperational += 1;
  }
  return { total: statuses.length, operational, notOperational, unknown, byStatus };
}
