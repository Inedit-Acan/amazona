import type { Incident, PipelineKillSwitchState } from "./api.ts";
import { emptyView, formatUtcDateTime, loadedView, plural, unusable, type BlockRow, type BlockStrip, type BlockView } from "./ceo-block-view.ts";
import { parseUtc } from "./dates.ts";
import { listOf, type ReadState } from "./read-state.ts";

// INCIDENCIAS ACTIVAS (M47, Commit 3B, D-3B-3). Hoy NO existe un modelo de riesgo empresarial (logístico, económico, legal o
// regulatorio): por eso el bloque se llama «Incidencias activas» y no «Riesgos activos». Lo que sí existe, con severidad REAL:
//
//   · las incidencias abiertas (`incidents`, `status = OPEN`, severidad LOW / MEDIUM / HIGH / CRITICAL; se registran a mano), y
//   · el kill switch del pipeline: `enabled === false` es «pipeline detenido por un operador». `enabled` es el estado NORMAL (y el valor
//     por defecto cuando no hay fila): solo `false` se enseña. Es una franja aparte: NO cuenta como incidencia y NO lleva severidad.
//
// Lo que no se muestra aquí: el estado técnico de un agente (FAILED, BLOCKED, DEGRADED: no es vivo y no tiene severidad), una ejecución
// fallida o parcial, el dinero en revisión (depende de la ventana de Ingresos) ni las revisiones posteriores (están en Decisiones).
// Una severidad fuera de las cuatro conocidas es un contrato roto (`ceo-block-contracts.ts`), nunca un valor por defecto.

export const INCIDENTS_BLOCK = {
  key: "incidencias",
  title: "Incidencias activas",
  tab: "Incidencias",
  seeAll: { href: "/status", label: "Ver todas" },
} as const;

/** La traducción de la severidad REAL de una incidencia. No hay otra severidad en estos bloques. */
export const SEVERITY_LABEL = { LOW: "Baja", MEDIUM: "Media", HIGH: "Alta", CRITICAL: "Crítica" } as const;
type Severity = keyof typeof SEVERITY_LABEL;

const SEVERITY_RANK: Record<Severity, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
const SEVERITY_LEVEL = { LOW: "low", MEDIUM: "medium", HIGH: "high", CRITICAL: "critical" } as const;

const EMPTY_TEXT = "Ninguna incidencia abierta ni pipeline detenido";
const NO_ROWS_TEXT = "Ninguna incidencia abierta.";

function incidentRow(incident: Incident): BlockRow {
  const severity = incident.severity as Severity;
  return {
    key: `incident:${incident.id}`,
    title: incident.title,
    subtitle: `Abierta ${formatUtcDateTime(parseUtc(incident.created_at))}`,
    tag: { text: SEVERITY_LABEL[severity], level: SEVERITY_LEVEL[severity] },
    detail: incident.description === null ? [] : [incident.description],
    provenance: {
      source: "incidents",
      entity: "incident",
      id: incident.id,
      status: incident.status,
      areaLabel: "Incidencia",
      at: incident.created_at,
      confidence: null,
      rationale: incident.description,
    },
  };
}

/** Severidad descendente (CRITICAL primero), luego la más reciente, y el id desempata. */
function bySeverityThenRecent(a: Incident, b: Incident): number {
  const rank = SEVERITY_RANK[a.severity as Severity] - SEVERITY_RANK[b.severity as Severity];
  if (rank !== 0) return rank;
  const at = parseUtc(a.created_at);
  const bt = parseUtc(b.created_at);
  if (at !== bt) return at > bt ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function pipelineStrip(killSwitch: PipelineKillSwitchState): BlockStrip | null {
  if (killSwitch.enabled === false) {
    return {
      text: "Pipeline detenido por un operador",
      detail: killSwitch.reason === null || killSwitch.reason === "" ? null : `Motivo: ${killSwitch.reason}`,
      provenance: {
        source: "pipeline_kill_switch",
        entity: "pipeline_kill_switch",
        id: null,
        status: "detenido",
        areaLabel: "Estado operativo",
        at: null,
        confidence: null,
        rationale: killSwitch.reason,
      },
    };
  }
  return null;
}

export function incidentsBlock(input: { incidents: ReadState<Incident[]>; killSwitch: ReadState<PipelineKillSwitchState> }): BlockView {
  const { incidents, killSwitch } = input;
  const failed = unusable([incidents, killSwitch]);
  if (failed) return failed;

  const open = (listOf(incidents) ?? []).filter((incident) => incident.status === "OPEN").sort(bySeverityThenRecent);
  const strip = killSwitch.kind === "loaded" ? pipelineStrip(killSwitch.data) : null;
  if (open.length === 0 && strip === null) return emptyView(EMPTY_TEXT);
  return loadedView({
    rows: open.map(incidentRow),
    countText: String(open.length),
    countLabel: `${open.length} ${plural(open.length, "incidencia abierta", "incidencias abiertas")}`,
    noRowsText: open.length === 0 ? NO_ROWS_TEXT : null,
    strip,
  });
}
