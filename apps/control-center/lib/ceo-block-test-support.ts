import type { Approval, Incident, PipelineKillSwitchState, PipelineReview, Product } from "./api.ts";
import type { BlocksSource } from "./ceo-block-reads.ts";
import type { ReadState } from "./read-state.ts";

// Apoyo común de las pruebas de los tres bloques ejecutivos del Director ejecutivo (M47, Commit 3B). No es una prueba: no acaba en
// `.test.ts`, así que `node --test` no lo ejecuta.

/** El instante de «ahora» de todas las pruebas: el 15 de octubre de 2026 a las 12:00 UTC. */
export const NOW = Date.parse("2026-10-15T12:00:00Z");
export const HOUR = 3_600_000;

const iso = (ms: number) => new Date(ms).toISOString();

export const approval = (id: string, over: Partial<Approval> = {}): Approval => ({
  id,
  decision_id: "dec-1",
  action: "launch_marketing_campaign",
  amount: 120,
  status: "PENDING",
  expires_at: iso(NOW + 24 * HOUR),
  resolved_at: null,
  resolved_by: null,
  ...over,
});

export const review = (id: string, over: Partial<PipelineReview> = {}): PipelineReview => ({
  id,
  pipeline_run_id: "run-1",
  kind: "ACTION_GATE",
  step: "marketing",
  action: "activate_ads",
  reasons: ["gasto sin autorizar"],
  status: "PENDING",
  resolved_at: null,
  resolved_by: null,
  correlation_id: "corr-1",
  ...over,
});

export const product = (id: string, over: Partial<Product> = {}): Product => ({
  id,
  name: `Producto ${id}`,
  category: "hogar",
  status: "CANDIDATE",
  created_by: "agent",
  source: "research",
  identity_key: null,
  also_known_as: [],
  ...over,
});

export const incident = (id: string, over: Partial<Incident> = {}): Incident => ({
  id,
  title: `Incidencia ${id}`,
  description: null,
  severity: "MEDIUM",
  status: "OPEN",
  resolved_at: null,
  created_at: iso(NOW - 2 * HOUR),
  ...over,
});

export const killSwitch = (over: Partial<PipelineKillSwitchState> = {}): PipelineKillSwitchState => ({
  enabled: true,
  reason: null,
  updated_by: null,
  ...over,
});

export const loaded = <T>(data: T[]): ReadState<T[]> => (data.length === 0 ? { kind: "empty" } : { kind: "loaded", data });
export const one = <T>(data: T): ReadState<T> => ({ kind: "loaded", data });
export const failed = (message = "No se pudo cargar x."): ReadState<never> => ({ kind: "error", message });

/** Una fuente completa con cinco lecturas que cuentan sus llamadas. */
export function fakeSource(over: Partial<BlocksSource> = {}): BlocksSource & { calls: Record<string, number> } {
  const calls: Record<string, number> = { listApprovals: 0, listPipelineReviews: 0, listProducts: 0, listIncidents: 0, getPipelineKillSwitch: 0 };
  const counted =
    <T>(name: string, value: () => Promise<T>) =>
    () => {
      calls[name] += 1;
      return value();
    };
  return {
    calls,
    listApprovals: counted("listApprovals", over.listApprovals ?? (async () => [])),
    listPipelineReviews: counted("listPipelineReviews", over.listPipelineReviews ?? (async () => [])),
    listProducts: counted("listProducts", over.listProducts ?? (async () => [])),
    listIncidents: counted("listIncidents", over.listIncidents ?? (async () => [])),
    getPipelineKillSwitch: counted("getPipelineKillSwitch", over.getPipelineKillSwitch ?? (async () => killSwitch())),
  };
}
