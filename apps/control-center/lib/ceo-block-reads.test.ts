import assert from "node:assert/strict";
import { test } from "node:test";
import { approval, fakeSource, HOUR, incident, killSwitch, NOW, product, review } from "./ceo-block-test-support.ts";
import { readBlocks } from "./ceo-block-reads.ts";
import { FAILURES, INVALID_PAYLOADS, LOOKS_LIKE_ABSENCE, TECHNICAL } from "./read-test-support.ts";

// Los lectores de los tres bloques ejecutivos (M47, Commit 3B): una sola ronda de lecturas (cinco peticiones, cada una UNA vez), sin
// ventana temporal, y un fallo o un contrato roto es `error` del bloque que lo sufre, nunca un vacío ni demostración.

const reject = (make: () => Error) => async (): Promise<never> => {
  throw make();
};

test("UNA sola ronda: cada una de las cinco lecturas se hace exactamente una vez", async () => {
  const source = fakeSource();
  await readBlocks(source, NOW);
  assert.deepEqual(source.calls, { listApprovals: 1, listPipelineReviews: 1, listProducts: 1, listIncidents: 1, getPipelineKillSwitch: 1 });
});

test("el selector 7/14/30 no existe para estos bloques: `readBlocks` no recibe ventana y su resultado no depende de nada más que de las lecturas y del instante", async () => {
  assert.equal(readBlocks.length, 2, "readBlocks(source, now): sin ventana, sin días");
  const make = () =>
    fakeSource({
      listApprovals: async () => [approval("a")],
      listProducts: async () => [product("p1")],
      listIncidents: async () => [incident("i1")],
    });
  const a = await readBlocks(make(), NOW);
  const b = await readBlocks(make(), NOW);
  assert.deepEqual(a, b);
});

test("con datos reales, los tres bloques se cargan cada uno con SU fuente", async () => {
  const { decisions, candidates, incidents } = await readBlocks(
    fakeSource({
      listApprovals: async () => [approval("a1", { expires_at: new Date(NOW + HOUR).toISOString() })],
      listPipelineReviews: async () => [review("g1")],
      listProducts: async () => [product("p1"), product("p2", { source: "manual" })],
      listIncidents: async () => [incident("i1", { severity: "HIGH" })],
      getPipelineKillSwitch: async () => killSwitch({ enabled: false, reason: "parada" }),
    }),
    NOW,
  );
  assert.equal(decisions.kind === "loaded" && decisions.count, 2);
  assert.equal(candidates.kind === "loaded" && candidates.count, 2);
  assert.equal(incidents.kind === "loaded" && incidents.count, 1);
  assert.equal(incidents.kind === "loaded" && incidents.strip?.text, "Pipeline detenido por un operador");
});

test("todo vacío ⇒ los tres bloques están VACÍOS (un hecho)", async () => {
  const { decisions, candidates, incidents } = await readBlocks(fakeSource(), NOW);
  assert.deepEqual([decisions.kind, candidates.kind, incidents.kind], ["empty", "empty", "empty"]);
});

test("una lectura que falla rompe SOLO el bloque que la usa, con el mensaje de esa lectura y nada técnico", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const approvals = await readBlocks(fakeSource({ listApprovals: reject(make) }), NOW);
    assert.deepEqual([approvals.decisions.kind, approvals.candidates.kind, approvals.incidents.kind], ["error", "empty", "empty"], name);

    const reviews = await readBlocks(fakeSource({ listPipelineReviews: reject(make) }), NOW);
    assert.equal(reviews.decisions.kind, "error", name);

    const products = await readBlocks(fakeSource({ listProducts: reject(make) }), NOW);
    assert.deepEqual([products.decisions.kind, products.candidates.kind, products.incidents.kind], ["empty", "error", "empty"], name);

    const incidents = await readBlocks(fakeSource({ listIncidents: reject(make) }), NOW);
    assert.deepEqual([incidents.decisions.kind, incidents.candidates.kind, incidents.incidents.kind], ["empty", "empty", "error"], name);

    const kill = await readBlocks(fakeSource({ getPipelineKillSwitch: reject(make) }), NOW);
    assert.equal(kill.incidents.kind, "error", name);

    for (const view of [approvals.decisions, reviews.decisions, products.candidates, incidents.incidents, kill.incidents]) {
      assert.equal(view.kind, "error");
      if (view.kind !== "error") continue;
      assert.doesNotMatch(view.message, TECHNICAL, `${name}: ${view.message}`);
      assert.doesNotMatch(view.message, LOOKS_LIKE_ABSENCE, `${name}: un fallo no se parece a una ausencia`);
    }
  }
});

test("una respuesta que no es una lista es ERROR, no vacío", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const { decisions, candidates, incidents } = await readBlocks(
      fakeSource({
        listApprovals: async () => payload as never,
        listProducts: async () => payload as never,
        listIncidents: async () => payload as never,
      }),
      NOW,
    );
    assert.deepEqual([decisions.kind, candidates.kind, incidents.kind], ["error", "error", "error"], name);
  }
});

test("un fallo NO se convierte en datos de demostración ni en una lista vacía: ningún bloque en error lleva filas", async () => {
  const { decisions, candidates, incidents } = await readBlocks(
    fakeSource({ listApprovals: reject(FAILURES["500"]), listProducts: reject(FAILURES["503"]), listIncidents: reject(FAILURES["red caída"]) }),
    NOW,
  );
  for (const view of [decisions, candidates, incidents]) assert.doesNotMatch(JSON.stringify(view), /"rows"|"count"|demo/i);
});

test("CONTRATO ROTO: una fila con una severidad desconocida es error del bloque de incidencias (no «Media» ni fila ignorada)", async () => {
  const { incidents } = await readBlocks(
    fakeSource({ listIncidents: async () => [incident("ok"), incident("x", { severity: "URGENT" as never })] }),
    NOW,
  );
  assert.equal(incidents.kind, "error");
  assert.match(incidents.kind === "error" ? incidents.message : "", /severidad/);
});

test("CONTRATO ROTO: una aprobación con un estado desconocido o un producto con un estado distinto de CANDIDATE rompe su bloque", async () => {
  const broken = await readBlocks(
    fakeSource({
      listApprovals: async () => [approval("a", { status: "PAUSED" as never })],
      listProducts: async () => [product("p", { status: "GO" })],
    }),
    NOW,
  );
  assert.equal(broken.decisions.kind, "error");
  assert.equal(broken.candidates.kind, "error");
});

test("el kill switch con `enabled` que no es booleano es error del bloque (no se interpreta como habilitado)", async () => {
  const { incidents } = await readBlocks(fakeSource({ getPipelineKillSwitch: async () => ({ enabled: "false", reason: null, updated_by: null }) as never }), NOW);
  assert.equal(incidents.kind, "error");
});

test("`now` decide qué está vencido: el mismo dato, otro instante, otro resultado", async () => {
  const source = () => fakeSource({ listApprovals: async () => [approval("a", { expires_at: new Date(NOW + HOUR).toISOString() })] });
  const antes = await readBlocks(source(), NOW);
  const despues = await readBlocks(source(), NOW + 2 * HOUR);
  assert.equal(antes.decisions.kind === "loaded" && antes.decisions.count, 1);
  assert.equal(despues.decisions.kind === "loaded" && despues.decisions.count, 0);
  assert.equal(despues.decisions.kind === "loaded" && despues.decisions.secondary.length, 1);
});
