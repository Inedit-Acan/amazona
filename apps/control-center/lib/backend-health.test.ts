import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  CHECKING_LABEL,
  checkBackend,
  classifyReadiness,
  HEALTH_LABEL,
  HEALTH_TIMEOUT_MS,
  HealthMonitor,
  healthLabel,
  INITIAL_HEALTH,
  type BackendHealthState,
  type HealthScheduler,
  type HealthVerdict,
} from "./backend-health.ts";

// La salud del backend de la cabecera (M47, Commit 1): el contrato de `/health/ready` y las reglas del monitor.

// --- Contrato ---------------------------------------------------------------------------------------------------

test("200 + {status: ok} es ready; 503 + {status: degraded} es degraded", () => {
  assert.equal(classifyReadiness({ status: 200, body: { status: "ok" } }), "ready");
  assert.equal(classifyReadiness({ status: 503, body: { status: "degraded" } }), "degraded");
});

test("cualquier otra respuesta NO se acepta como «bien»", () => {
  const cases: [string, number, unknown][] = [
    ["200 con cuerpo inesperado", 200, { status: "up" }],
    ["200 sin cuerpo", 200, null],
    ["200 con cuerpo de texto", 200, "ok"],
    ["200 degraded (contradice el contrato)", 200, { status: "degraded" }],
    ["503 con ok (contradice el contrato)", 503, { status: "ok" }],
    ["500", 500, { status: "ok" }],
    ["404", 404, { detail: "Not Found" }],
    ["401", 401, { detail: "no token" }],
    ["503 sin cuerpo", 503, null],
    ["204", 204, null],
  ];
  for (const [name, status, body] of cases) assert.equal(classifyReadiness({ status, body }), "unavailable", name);
});

test("checkBackend: rechazo de red, fallo y timeout son unavailable; nunca lanza", async () => {
  assert.equal(await checkBackend(async () => ({ status: 200, body: { status: "ok" } })), "ready");
  assert.equal(await checkBackend(async () => ({ status: 503, body: { status: "degraded" } })), "degraded");
  assert.equal(await checkBackend(async () => { throw new TypeError("fetch failed"); }), "unavailable");
  assert.equal(await checkBackend(async () => { throw new DOMException("aborted", "AbortError"); }), "unavailable");
  // Un backend que no responde: la comprobación termina igual, aunque la petición ignore la señal.
  assert.equal(await checkBackend(() => new Promise(() => {}), 20), "unavailable");
});

test("el timeout cancela la petición (señal abortada)", async () => {
  let aborted = false;
  const verdict = await checkBackend(
    (signal) => new Promise((_, reject) => signal.addEventListener("abort", () => { aborted = true; reject(new Error("aborted")); })),
    20,
  );
  assert.equal(verdict, "unavailable");
  assert.equal(aborted, true);
});

// --- Etiquetas ---------------------------------------------------------------------------------------------------

test("el estado inicial es «comprobando» y nunca «operativo»; «Sistema operativo» no existe", () => {
  assert.equal(INITIAL_HEALTH.kind, "checking");
  assert.equal(healthLabel(INITIAL_HEALTH), CHECKING_LABEL);
  assert.notEqual(healthLabel(INITIAL_HEALTH), HEALTH_LABEL.ready);
  assert.deepEqual(HEALTH_LABEL, {
    ready: "Backend operativo",
    degraded: "Backend degradado",
    unavailable: "Backend no disponible",
  });
  for (const label of [...Object.values(HEALTH_LABEL), CHECKING_LABEL]) assert.doesNotMatch(label, /sistema/i);
});

// --- Monitor -----------------------------------------------------------------------------------------------------

function harness(verdicts: HealthVerdict[] | (() => Promise<HealthVerdict>), minGapMs = 5_000) {
  let now = 1_000_000;
  const states: BackendHealthState[] = [];
  const intervals: { handler: () => void; ms: number; cleared: boolean }[] = [];
  const scheduler: HealthScheduler = {
    setInterval: (handler, ms) => {
      const entry = { handler, ms, cleared: false };
      intervals.push(entry);
      return entry;
    },
    clearInterval: (handle) => {
      (handle as { cleared: boolean }).cleared = true;
    },
  };
  const calls: number[] = [];
  const pending: ((verdict: HealthVerdict) => void)[] = [];
  const queue = Array.isArray(verdicts) ? [...verdicts] : null;
  const monitor = new HealthMonitor({
    check: () => {
      calls.push(now);
      if (typeof verdicts === "function") return verdicts();
      const next = queue!.shift();
      if (next !== undefined) return Promise.resolve(next);
      return new Promise<HealthVerdict>((resolve) => pending.push(resolve));
    },
    now: () => now,
    onChange: (state) => states.push(state),
    scheduler,
    pollMs: 60_000,
    minGapMs,
  });
  return {
    monitor,
    states,
    calls,
    intervals,
    pending,
    tick: (ms: number) => { now += ms; },
    flush: () => new Promise((resolve) => setImmediate(resolve)),
    active: () => intervals.filter((entry) => !entry.cleared),
  };
}

test("al montar con la pestaña visible: una comprobación y un temporizador de 60 s", async () => {
  const h = harness(["ready"]);
  h.monitor.start(true);
  await h.flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.active().length, 1);
  assert.equal(h.active()[0].ms, 60_000);
  assert.deepEqual(h.states.at(-1), { kind: "known", verdict: "ready", checkedAt: 1_000_000, refreshing: false });
});

test("con la pestaña oculta al montar: ni petición ni temporizador", async () => {
  const h = harness(["ready"]);
  h.monitor.start(false);
  await h.flush();
  assert.equal(h.calls.length, 0);
  assert.equal(h.intervals.length, 0);
  assert.equal(h.monitor.current.kind, "checking");
});

test("al ocultarse la pestaña se para el polling; al volver comprueba y lo reanuda", async () => {
  const h = harness(["ready", "ready"]);
  h.monitor.start(true);
  await h.flush();
  h.monitor.setVisible(false);
  assert.equal(h.active().length, 0, "con la pestaña oculta no puede haber temporizador");
  h.tick(30_000);
  h.monitor.focus(); // el foco con la pestaña oculta no dispara nada
  assert.equal(h.calls.length, 1);
  h.monitor.setVisible(true);
  await h.flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.active().length, 1);
});

test("una sola petición activa: los disparadores durante una consulta se ignoran", async () => {
  const h = harness([]); // la comprobación no termina hasta que se resuelva a mano
  h.monitor.start(true);
  h.tick(10_000);
  assert.equal(h.monitor.trigger("poll"), false);
  assert.equal(h.monitor.trigger("focus"), false);
  assert.equal(h.monitor.trigger("visible"), false);
  assert.equal(h.calls.length, 1);
  h.pending[0]("ready");
  await h.flush();
  assert.equal(h.monitor.trigger("poll"), true);
  assert.equal(h.calls.length, 2);
});

test("«volver a visible» y «recuperar el foco» juntos no duplican la petición (hueco mínimo)", async () => {
  const h = harness(["ready", "ready", "ready"]);
  h.monitor.start(true);
  await h.flush();
  h.tick(1_000);
  h.monitor.setVisible(false);
  h.monitor.setVisible(true); // visible, a 1 s de la anterior
  h.monitor.focus();
  await h.flush();
  assert.equal(h.calls.length, 1, "dos disparadores seguidos no pueden ser tres peticiones");
  h.tick(10_000);
  h.monitor.focus();
  await h.flush();
  assert.equal(h.calls.length, 2);
});

test("el polling de 60 s llama aunque haya pasado poco desde la anterior solo si no hay una en vuelo", async () => {
  const h = harness(["ready", "ready"]);
  h.monitor.start(true);
  await h.flush();
  h.tick(60_000);
  h.active()[0].handler();
  await h.flush();
  assert.equal(h.calls.length, 2);
});

test("un fallo es `unavailable`: no se conserva en silencio el último verde", async () => {
  const h = harness(["ready", "unavailable"]);
  h.monitor.start(true);
  await h.flush();
  assert.equal((h.monitor.current as { verdict: string }).verdict, "ready");
  h.tick(60_000);
  h.monitor.trigger("poll");
  await h.flush();
  const last = h.states.at(-1)!;
  assert.equal(last.kind, "known");
  assert.equal((last as { verdict: string }).verdict, "unavailable");
  assert.equal((last as { refreshing: boolean }).refreshing, false);
});

test("durante una consulta nueva el veredicto anterior se marca `refreshing`, no `ready` confirmado", async () => {
  const h = harness(["ready"]);
  h.monitor.start(true);
  await h.flush();
  h.tick(60_000);
  h.monitor.trigger("poll"); // la cola está vacía: queda en vuelo
  const refreshing = h.states.at(-1)!;
  assert.deepEqual(refreshing, { kind: "known", verdict: "ready", checkedAt: 1_000_000, refreshing: true });
  h.pending[0]("degraded");
  await h.flush();
  assert.deepEqual(h.states.at(-1), { kind: "known", verdict: "degraded", checkedAt: 1_060_000, refreshing: false });
});

test("una comprobación que lanza se trata como `unavailable`", async () => {
  const h = harness(async () => { throw new Error("boom"); });
  h.monitor.start(true);
  await h.flush();
  assert.equal((h.monitor.current as { verdict: string }).verdict, "unavailable");
});

test("dispose: limpia el temporizador y descarta la respuesta que llegue tarde", async () => {
  const h = harness([]);
  h.monitor.start(true);
  const before = h.states.length;
  h.monitor.dispose();
  assert.equal(h.active().length, 0);
  h.pending[0]("ready");
  await h.flush();
  assert.equal(h.states.length, before, "no se puede emitir tras desmontar");
  assert.equal(h.monitor.trigger("poll"), false);
  h.monitor.setVisible(false);
  h.monitor.setVisible(true);
  assert.equal(h.intervals.length, 1, "tras dispose no se crean temporizadores");
});

test("tras un veredicto bueno, una comprobación que LANZA da `unavailable`: no se conserva el último verde", async () => {
  let calls = 0;
  const h = harness(async () => {
    calls += 1;
    if (calls === 1) return "ready";
    throw new Error("boom");
  });
  h.monitor.start(true);
  await h.flush();
  assert.equal((h.monitor.current as { verdict: string }).verdict, "ready");
  h.tick(60_000);
  h.monitor.trigger("poll");
  await h.flush();
  const last = h.monitor.current as { kind: string; verdict: string; refreshing: boolean };
  assert.equal(last.kind, "known");
  assert.equal(last.verdict, "unavailable");
  assert.equal(last.refreshing, false);
});

test("el techo de la comprobación supera el connect_timeout de la BD del backend (si no, `degraded` se vería como «no disponible»)", () => {
  const session = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../../backend/app/db/session.py"), "utf8");
  const match = session.match(/"connect_timeout":\s*(\d+)/);
  assert.ok(match, "no se encontró connect_timeout en backend/app/db/session.py: ¿se movió?");
  const connectSeconds = Number(match[1]);
  assert.ok(
    HEALTH_TIMEOUT_MS > connectSeconds * 1000,
    `HEALTH_TIMEOUT_MS (${HEALTH_TIMEOUT_MS} ms) no supera el connect_timeout del backend (${connectSeconds} s): con la BD caída un 503 degraded se leería como «no disponible»`,
  );
});
