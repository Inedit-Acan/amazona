import assert from "node:assert/strict";
import { test } from "node:test";
import type { BackendHealthState } from "./backend-health.ts";
import { INITIAL_HEALTH } from "./backend-health.ts";
import { createHealthStore } from "./backend-health-store.ts";

// Un solo monitor de salud por pestaña (M47, Commit 2): la cabecera del shell y la del Director ejecutivo lo comparten.

function harness() {
  let attached = 0;
  let detached = 0;
  let publish: (state: BackendHealthState) => void = () => {};
  const store = createHealthStore({
    attach(p) {
      attached += 1;
      publish = p;
      return () => {
        detached += 1;
      };
    },
  });
  return { store, counts: () => ({ attached, detached }), publish: (state: BackendHealthState) => publish(state) };
}

const READY: BackendHealthState = { kind: "known", verdict: "ready", checkedAt: 1, refreshing: false };

test("dos suscriptores comparten UN monitor: no hay dos peticiones por disparo", () => {
  const h = harness();
  const unsubscribeA = h.store.subscribe(() => {});
  const unsubscribeB = h.store.subscribe(() => {});
  assert.deepEqual(h.counts(), { attached: 1, detached: 0 });
  assert.equal(h.store.subscribers(), 2);
  unsubscribeA();
  assert.deepEqual(h.counts(), { attached: 1, detached: 0 }, "mientras quede uno, el monitor sigue vivo");
  unsubscribeB();
  assert.deepEqual(h.counts(), { attached: 1, detached: 1 }, "el último en irse destruye el monitor (limpieza)");
});

test("todos los suscriptores reciben el mismo estado", () => {
  const h = harness();
  const seen: BackendHealthState[][] = [[], []];
  const a = h.store.subscribe(() => seen[0].push(h.store.getSnapshot()));
  const b = h.store.subscribe(() => seen[1].push(h.store.getSnapshot()));
  h.publish(READY);
  assert.deepEqual(seen[0], [READY]);
  assert.deepEqual(seen[1], [READY]);
  assert.equal(h.store.getSnapshot(), READY);
  a();
  b();
});

test("el estado inicial es «comprobando», nunca un veredicto: tampoco en el servidor", () => {
  const h = harness();
  assert.equal(h.store.getSnapshot(), INITIAL_HEALTH);
  assert.equal(h.store.getServerSnapshot().kind, "checking");
});

test("sin suscriptores el estado vuelve a «comprobando»: un veredicto antiguo no se sirve como actual", () => {
  const h = harness();
  const unsubscribe = h.store.subscribe(() => {});
  h.publish(READY);
  assert.equal(h.store.getSnapshot().kind, "known");
  unsubscribe();
  assert.equal(h.store.getSnapshot().kind, "checking");
  // Y una nueva suscripción arranca un monitor nuevo.
  const again = h.store.subscribe(() => {});
  assert.equal(h.counts().attached, 2);
  again();
});

test("darse de baja dos veces no destruye el monitor de otro", () => {
  const h = harness();
  const a = h.store.subscribe(() => {});
  const b = h.store.subscribe(() => {});
  a();
  a();
  assert.deepEqual(h.counts(), { attached: 1, detached: 0 });
  b();
  assert.deepEqual(h.counts(), { attached: 1, detached: 1 });
});
