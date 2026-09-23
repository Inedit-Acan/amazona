import assert from "node:assert/strict";
import { test } from "node:test";
import { overallStatus, realSignals, workerSignal, type HealthSignal, type WorkerSignal } from "./status.ts";

const signal = (over: Partial<HealthSignal> = {}): HealthSignal => ({
  apiReachable: true,
  latencyMs: 42,
  health: { database: "ok", supabase_configured: true },
  ...over,
});

const workers = (over: Partial<WorkerSignal> = {}): WorkerSignal => ({ runs: 10, failures: 0, avgDurationMs: 120, ...over });

test("realSignals: con todo bien, los seis servicios con señal están operativos", () => {
  const real = realSignals(signal(), workers());
  assert.deepEqual(Object.keys(real), ["frontend", "api", "postgres", "auth", "storage", "workers"]);
  assert.ok(Object.values(real).every((s) => s.state === "operational"));
  // Solo se cronometran la API y las ejecuciones de agentes.
  assert.equal(real.api.measuredMs, 42);
  assert.equal(real.workers.measuredMs, 120);
  assert.equal(real.postgres.measuredMs, null);
});

test("realSignals: el backend caído tumba la API y deja el resto sin señal", () => {
  const real = realSignals(signal({ apiReachable: false, latencyMs: null }), workers());
  assert.equal(real.frontend.state, "operational");
  assert.equal(real.api.state, "down");
  assert.equal(real.api.measuredMs, null);
  assert.equal(real.postgres.state, "no_signal");
  assert.equal(real.auth.state, "no_signal");
  assert.equal(real.storage.state, "no_signal");
});

test("realSignals: base de datos con error cae; Supabase sin configurar se queda sin señal", () => {
  const real = realSignals(signal({ health: { database: "error", supabase_configured: false } }), workers());
  assert.equal(real.postgres.state, "down");
  assert.equal(real.auth.state, "no_signal");
  assert.equal(real.storage.state, "no_signal");
  assert.equal(real.auth.note, real.storage.note);
});

test("realSignals: los workers dependen de sus ejecuciones, no de la comprobación de salud", () => {
  assert.equal(realSignals(signal(), workers({ runs: 0, failures: 0, avgDurationMs: null })).workers.state, "no_signal");
  assert.equal(realSignals(signal(), workers({ runs: 4, failures: 4 })).workers.state, "down");
  assert.equal(realSignals(signal(), workers({ runs: 4, failures: 1 })).workers.state, "operational");
});

test("workerSignal resume las ejecuciones reales", () => {
  assert.deepEqual(workerSignal([]), { runs: 0, failures: 0, avgDurationMs: null });
  assert.deepEqual(
    workerSignal([
      { success: true, duration_ms: 100 },
      { success: false, duration_ms: 300 },
    ]),
    { runs: 2, failures: 1, avgDurationMs: 200 },
  );
});

test("overallStatus prioriza backend caído > base de datos > incidentes abiertos > operativo", () => {
  assert.equal(overallStatus({ signal: signal({ apiReachable: false }), openIncidents: 3 }).title, "Backend caído");
  assert.equal(overallStatus({ signal: signal({ health: { database: "error", supabase_configured: true } }), openIncidents: 3 }).tone, "bad");
  const withIncidents = overallStatus({ signal: signal(), openIncidents: 2 });
  assert.equal(withIncidents.title, "2 incidentes activos");
  assert.equal(withIncidents.tone, "warn");
  assert.equal(overallStatus({ signal: signal(), openIncidents: 1 }).title, "1 incidente activo");
  const ok = overallStatus({ signal: signal(), openIncidents: 0 });
  assert.equal(ok.title, "Sistema operativo");
  assert.equal(ok.tone, "ok");
});
