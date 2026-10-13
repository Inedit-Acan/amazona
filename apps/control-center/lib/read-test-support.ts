import type { Agent, AgentExecution, Approval, PipelineReview, Product } from "./api.ts";
import type { DashboardSource } from "./dashboard-reads.ts";

// Apoyo común de las pruebas de lectura (M46, Commit 6). No es una prueba: no acaba en `.test.ts`, así que `node --test`
// no lo ejecuta y puede importarse sin volver a registrar pruebas.

/** Lo que un mensaje para el usuario no puede contener: estados HTTP, errores de red, trazas o nombres de excepción. */
export const TECHNICAL =
  /\b[45]\d\d\b|fetch failed|ECONNREFUSED|ENOTFOUND|Traceback|HTTP|SyntaxError|TypeError|Unexpected token|undefined|\[object/i;

/** Lo que un fallo de lectura nunca puede parecer: una ausencia de datos o un cero. */
export const LOOKS_LIKE_ABSENCE = /Sin datos|No hay|Nada esperando|Sin agentes|Sin ejecuciones|^0\b|\b0 \/ 0\b|0 %/;

export const apiError = (status: number, detail = "internal detail 42") =>
  Object.assign(new Error(detail), { status, detail });

/** Todas las formas en que una lectura puede fallar. */
export const FAILURES: Record<string, () => Error> = {
  "401": () => apiError(401, "no token"),
  "403": () => apiError(403, "forbidden"),
  "404": () => apiError(404, "not found"),
  "422": () => apiError(422, "bad request"),
  "500": () => apiError(500, "Traceback (most recent call last): boom"),
  "503": () => apiError(503, "upstream down"),
  "red caída": () => new TypeError("fetch failed"),
  "conexión rechazada": () => Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNREFUSED" } }),
  "cuerpo no JSON": () => new SyntaxError("Unexpected token < in JSON at position 0"),
};

/** Respuestas con la forma equivocada: no son una lista, así que no se leen como «lista vacía». */
export const INVALID_PAYLOADS: ReadonlyArray<readonly [string, unknown]> = [
  ["null", null],
  ["undefined", undefined],
  ["un objeto", {}],
  ["un objeto con detail", { detail: "x" }],
  ["una cadena", "oops"],
  ["un número", 42],
  ["un booleano", false],
];

// --- Fixtures ---------------------------------------------------------------------------------------------------

export const NOW = Date.UTC(2026, 9, 14, 12);

export const agent = (id: string, status = "AVAILABLE"): Agent => ({
  id,
  name: `Agente ${id}`,
  role: "product",
  capabilities: ["research"],
  status,
  reliability_score: 1,
  version: "1.0.0",
  cost_profile: {},
});

export const execution = (id: string, agentId: string, at = NOW - 3_600_000): AgentExecution => ({
  id,
  agent_id: agentId,
  capability: "research",
  duration_ms: 1200,
  success: true,
  correlation_id: `corr-${id}`,
  created_at: new Date(at).toISOString(),
});

export const approval = (id: string): Approval => ({
  id,
  decision_id: `decision-${id}`,
  action: "LAUNCH",
  amount: 250,
  status: "PENDING",
  expires_at: new Date(NOW + 86_400_000).toISOString(),
  resolved_at: null,
  resolved_by: null,
  created_at: new Date(NOW - 7_200_000).toISOString(),
} as Approval);

export const review = (id: string): PipelineReview =>
  ({
    id,
    pipeline_run_id: `run-${id}`,
    kind: "ACTION_GATE",
    step: "marketing",
    action: "activate_ads",
    reasons: ["requires approval"],
    status: "PENDING",
    resolved_at: null,
    resolved_by: null,
    correlation_id: `corr-${id}`,
    created_at: new Date(NOW - 3_600_000).toISOString(),
  }) as unknown as PipelineReview;

export const product = (id: string, category = "electronics"): Product =>
  ({ id, name: `Producto ${id}`, category, status: "ACTIVE", created_by: "tester", source: "research" }) as Product;

/** Una `DashboardSource` con datos sanos por defecto y que cuenta cuántas veces se llama a cada lectura. */
export function fakeSource(
  overrides: Partial<Record<keyof DashboardSource, (...args: never[]) => Promise<unknown>>> = {},
  data: { products?: Product[] } = {},
): { source: DashboardSource; calls: Record<string, number> } {
  const calls: Record<string, number> = {};
  const defaults: Record<keyof DashboardSource, (...args: never[]) => Promise<unknown>> = {
    listProducts: async () => data.products ?? [product("p1"), product("p2")],
    listAgents: async () => [agent("a1"), agent("a2", "OFFLINE")],
    listAgentExecutions: async () => [execution("e1", "a1")],
    listApprovals: async () => [approval("ap1")],
    listPipelineReviews: async () => [review("rv1")],
    listProductSuppliers: async () => [],
    listProductEconomics: async () => [],
    listProductLegal: async () => [],
    listProductStorefronts: async () => [],
    listProductCampaigns: async () => [],
  };
  const source = {} as Record<string, unknown>;
  for (const key of Object.keys(defaults) as Array<keyof DashboardSource>) {
    const read = overrides[key] ?? defaults[key];
    source[key] = (...args: never[]) => {
      calls[key] = (calls[key] ?? 0) + 1;
      return read(...args);
    };
  }
  return { source: source as unknown as DashboardSource, calls };
}
