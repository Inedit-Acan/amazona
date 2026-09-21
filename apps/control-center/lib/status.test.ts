import assert from "node:assert/strict";
import { test } from "node:test";
import { overallStatus, serviceRows, serviceSummary, type HealthSignal } from "./status.ts";

const signal = (over: Partial<HealthSignal> = {}): HealthSignal => ({
  apiReachable: true,
  latencyMs: 42,
  health: { database: "ok", supabase_configured: true },
  ...over,
});

test("serviceRows: con todo bien, frontend, API, base de datos y Supabase operativos; solo la API lleva latencia", () => {
  const rows = serviceRows(signal());
  assert.deepEqual(rows.map((r) => [r.id, r.state]), [
    ["frontend", "operational"],
    ["api", "operational"],
    ["database", "operational"],
    ["supabase", "operational"],
  ]);
  assert.equal(rows.find((r) => r.id === "api")?.latencyMs, 42);
  assert.equal(rows.find((r) => r.id === "database")?.latencyMs, null);
});

test("serviceRows: backend caído deja la base de datos y Supabase sin señal; base de datos con error cae", () => {
  const down = serviceRows(signal({ apiReachable: false, latencyMs: null }));
  assert.deepEqual(down.map((r) => r.state), ["operational", "down", "no_signal", "no_signal"]);
  assert.equal(down.find((r) => r.id === "api")?.latencyMs, null);
  const dbDown = serviceRows(signal({ health: { database: "error", supabase_configured: false } }));
  assert.equal(dbDown.find((r) => r.id === "database")?.state, "down");
  assert.equal(dbDown.find((r) => r.id === "supabase")?.state, "no_signal");
});

test("serviceSummary cuenta operativos, caídos y con señal", () => {
  assert.deepEqual(serviceSummary(serviceRows(signal())), { operational: 4, down: 0, withSignal: 4 });
  assert.deepEqual(serviceSummary(serviceRows(signal({ health: { database: "error", supabase_configured: false } }))), {
    operational: 2,
    down: 1,
    withSignal: 3,
  });
});

test("overallStatus prioriza backend caído > base de datos > incidentes abiertos > operativo", () => {
  assert.equal(overallStatus({ signal: signal({ apiReachable: false }), openIncidents: 3 }).title, "Backend caído");
  assert.equal(overallStatus({ signal: signal({ health: { database: "error", supabase_configured: true } }), openIncidents: 3 }).tone, "bad");
  const withIncidents = overallStatus({ signal: signal(), openIncidents: 2 });
  assert.equal(withIncidents.title, "2 incidentes activos");
  assert.equal(withIncidents.tone, "warn");
  assert.equal(overallStatus({ signal: signal(), openIncidents: 1 }).title, "1 incidente activo");
  const ok = overallStatus({ signal: signal(), openIncidents: 0 });
  assert.equal(ok.title, "Operativo");
  assert.equal(ok.tone, "ok");
});
