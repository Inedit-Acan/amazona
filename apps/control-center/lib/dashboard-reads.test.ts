import assert from "node:assert/strict";
import { test } from "node:test";
import { PRODUCT_LIMIT, readDashboard, type CatalogEntry, type DashboardReads, type DashboardSource } from "./dashboard-reads.ts";
import { projectCodeFor } from "./projects-view.ts";
import type { ReadState } from "./read-state.ts";
import {
  agent,
  approval,
  execution,
  fakeSource,
  FAILURES,
  INVALID_PAYLOADS,
  LOOKS_LIKE_ABSENCE,
  product,
  review,
  TECHNICAL,
} from "./read-test-support.ts";

// Las 9 lecturas silenciosas del Panel (M46, Commit 6), una por una. Cada una se prueba con: datos, vacío válido, todos los
// fallos (401, 403, 404, 422, 500, 503, red caída, conexión rechazada, cuerpo no JSON), carga útil inválida, recuperación
// al repetirla, aislamiento (su fallo no toca las demás) y que cada intento es UNA petición.

type Read = {
  name: string;
  method: keyof DashboardSource;
  pick: (reads: DashboardReads) => ReadState<unknown>;
  data: () => unknown[];
};

const GLOBAL_READS: Read[] = [
  { name: "1 · agentes", method: "listAgents", pick: (r) => r.agents, data: () => [agent("a1"), agent("a2")] },
  { name: "2 · ejecuciones", method: "listAgentExecutions", pick: (r) => r.executions, data: () => [execution("e1", "a1")] },
  { name: "3 · aprobaciones", method: "listApprovals", pick: (r) => r.approvals, data: () => [approval("ap1")] },
  { name: "4 · revisiones de pipeline", method: "listPipelineReviews", pick: (r) => r.reviews, data: () => [review("rv1")] },
];

const PRODUCT_READS: Array<Omit<Read, "pick"> & { pick: (entry: CatalogEntry) => ReadState<unknown> }> = [
  { name: "5 · proveedores", method: "listProductSuppliers", pick: (e) => e.quotes, data: () => [{ id: "q1" }] },
  { name: "6 · economía", method: "listProductEconomics", pick: (e) => e.economics, data: () => [{ id: "ec1" }] },
  { name: "7 · legal", method: "listProductLegal", pick: (e) => e.legal, data: () => [{ id: "lg1" }] },
  { name: "8 · tiendas", method: "listProductStorefronts", pick: (e) => e.storefronts, data: () => [{ id: "st1" }] },
  { name: "9 · campañas", method: "listProductCampaigns", pick: (e) => e.campaigns, data: () => [{ id: "cm1" }] },
];

const failing = (make: () => Error) => async () => {
  throw make();
};

// --- Las cuatro lecturas globales ---------------------------------------------------------------------------------

for (const read of GLOBAL_READS) {
  test(`${read.name}: con datos es \`loaded\` y con una respuesta vacía válida es \`empty\``, async () => {
    const loaded = await readDashboard(fakeSource({ [read.method]: async () => read.data() }).source);
    const empty = await readDashboard(fakeSource({ [read.method]: async () => [] }).source);

    assert.equal(read.pick(loaded).kind, "loaded");
    assert.equal(read.pick(empty).kind, "empty");
  });

  for (const [failure, make] of Object.entries(FAILURES)) {
    test(`${read.name}: un fallo («${failure}») es \`error\` con un texto neutro; nunca \`empty\`, nunca un dato`, async () => {
      const reads = await readDashboard(fakeSource({ [read.method]: failing(make) }).source);
      const state = read.pick(reads);

      assert.equal(state.kind, "error");
      if (state.kind !== "error") return;
      assert.doesNotMatch(state.message, TECHNICAL, `texto técnico: ${state.message}`);
      assert.doesNotMatch(state.message, LOOKS_LIKE_ABSENCE, `el fallo se dice como ausencia: ${state.message}`);
    });
  }

  for (const [payload, value] of INVALID_PAYLOADS) {
    test(`${read.name}: una respuesta inválida (${payload}) es \`error\`, no una lista vacía`, async () => {
      const reads = await readDashboard(fakeSource({ [read.method]: async () => value }).source);

      assert.equal(read.pick(reads).kind, "error");
    });
  }

  test(`${read.name}: su fallo no cambia ninguna de las demás lecturas`, async () => {
    const baseline = await readDashboard(fakeSource().source);
    const reads = await readDashboard(fakeSource({ [read.method]: failing(FAILURES["500"]) }).source);

    for (const other of GLOBAL_READS.filter((candidate) => candidate.method !== read.method)) {
      assert.deepEqual(other.pick(reads), other.pick(baseline), `${other.name} cambió por el fallo de ${read.name}`);
    }
    assert.deepEqual(reads.products, baseline.products);
    assert.deepEqual(reads.catalog, baseline.catalog);
  });

  test(`${read.name}: recuperación — tras un error, repetir la lectura vuelve a dar datos`, async () => {
    let healthy = false;
    const { source } = fakeSource({
      [read.method]: async () => {
        if (!healthy) throw FAILURES["503"]();
        return read.data();
      },
    });

    const first = await readDashboard(source);
    healthy = true;
    const second = await readDashboard(source);

    assert.equal(read.pick(first).kind, "error");
    assert.equal(read.pick(second).kind, "loaded");
  });

  test(`${read.name}: cada intento es UNA petición, aunque falle (sin reintentos automáticos)`, async () => {
    const { source, calls } = fakeSource({ [read.method]: failing(FAILURES["503"]) });

    await readDashboard(source);

    assert.equal(calls[read.method], 1);
  });
}

// --- Las cinco lecturas por producto -------------------------------------------------------------------------------

for (const read of PRODUCT_READS) {
  test(`${read.name}: con datos es \`loaded\` y vacía válida es \`empty\`, producto a producto`, async () => {
    const reads = await readDashboard(
      fakeSource({ [read.method]: async (id: never) => (String(id) === "p1" ? read.data() : []) }).source,
    );

    assert.equal(read.pick(reads.catalog[0]).kind, "loaded");
    assert.equal(read.pick(reads.catalog[1]).kind, "empty");
  });

  for (const [failure, make] of Object.entries(FAILURES)) {
    test(`${read.name}: un fallo («${failure}») es \`error\` y no lo es \`empty\``, async () => {
      const reads = await readDashboard(fakeSource({ [read.method]: failing(make) }).source);

      for (const entry of reads.catalog) {
        const state = read.pick(entry);
        assert.equal(state.kind, "error");
        if (state.kind === "error") {
          assert.doesNotMatch(state.message, TECHNICAL);
          assert.doesNotMatch(state.message, LOOKS_LIKE_ABSENCE);
        }
      }
    });
  }

  for (const [payload, value] of INVALID_PAYLOADS) {
    test(`${read.name}: una respuesta inválida (${payload}) es \`error\``, async () => {
      const reads = await readDashboard(fakeSource({ [read.method]: async () => value }).source);

      assert.ok(reads.catalog.every((entry) => read.pick(entry).kind === "error"));
    });
  }

  test(`${read.name}: si falla solo para un producto, el otro conserva su dato y las otras cuatro lecturas no cambian`, async () => {
    const baseline = await readDashboard(fakeSource().source);
    const reads = await readDashboard(
      fakeSource({
        [read.method]: async (id: never) => {
          if (String(id) === "p1") throw FAILURES["500"]();
          return read.data();
        },
      }).source,
    );

    assert.equal(read.pick(reads.catalog[0]).kind, "error");
    assert.equal(read.pick(reads.catalog[1]).kind, "loaded");
    for (const other of PRODUCT_READS.filter((candidate) => candidate.method !== read.method)) {
      assert.deepEqual(other.pick(reads.catalog[0]), other.pick(baseline.catalog[0]));
    }
  });

  test(`${read.name}: recuperación tras un error`, async () => {
    let healthy = false;
    const { source } = fakeSource({
      [read.method]: async () => {
        if (!healthy) throw FAILURES["red caída"]();
        return read.data();
      },
    });

    const first = await readDashboard(source);
    healthy = true;
    const second = await readDashboard(source);

    assert.equal(read.pick(first.catalog[0]).kind, "error");
    assert.equal(read.pick(second.catalog[0]).kind, "loaded");
  });

  test(`${read.name}: una petición por producto, aunque falle`, async () => {
    const { source, calls } = fakeSource({ [read.method]: failing(FAILURES["503"]) });

    await readDashboard(source);

    assert.equal(calls[read.method], 2);
  });
}

// --- El catálogo y el tope de lectura ------------------------------------------------------------------------------

test("el catálogo: un fallo es `error` y no se leen los productos (nada que leer ≠ catálogo vacío)", async () => {
  const { source, calls } = fakeSource({ listProducts: failing(FAILURES["503"]) });

  const reads = await readDashboard(source);

  assert.equal(reads.products.kind, "error");
  assert.deepEqual(reads.catalog, []);
  assert.deepEqual(reads.unreadProductIds, []);
  assert.equal(calls.listProductSuppliers ?? 0, 0, "no se piden proveedores de un catálogo que no se pudo leer");
  // Y las demás lecturas siguen su curso.
  assert.equal(reads.agents.kind, "loaded");
  assert.equal(reads.approvals.kind, "loaded");
});

test("el catálogo: vacío válido es `empty` y no hay productos que leer", async () => {
  const reads = await readDashboard(fakeSource({}, { products: [] }).source);

  assert.equal(reads.products.kind, "empty");
  assert.deepEqual(reads.catalog, []);
});

test(`los productos que pasan del tope de ${PRODUCT_LIMIT} no se leen y se anotan como \`unread\`, no como «sin análisis»`, async () => {
  const many = Array.from({ length: PRODUCT_LIMIT + 3 }, (_, index) => product(`p${index}`));
  const { source, calls } = fakeSource({}, { products: many });

  const reads = await readDashboard(source);

  assert.equal(reads.catalog.length, PRODUCT_LIMIT);
  assert.deepEqual(reads.unreadProductIds, ["p8", "p9", "p10"]);
  assert.equal(calls.listProductSuppliers, PRODUCT_LIMIT);
  assert.ok(!reads.catalog.some((entry) => reads.unreadProductIds.includes(entry.product.id)));
});

test("el código de proyecto de cada producto sale de su posición, como antes (`projectCodeFor`)", async () => {
  const reads = await readDashboard(fakeSource().source);

  assert.deepEqual(reads.catalog.map((entry) => entry.projectCode), [projectCodeFor(0), projectCodeFor(1)]);
});

test("el Panel solo LEE: la fuente no expone ninguna operación de escritura", () => {
  const { source } = fakeSource();

  for (const method of Object.keys(source)) {
    assert.match(method, /^list/, `${method} no es una lectura`);
  }
});

test("todo a la vez: si falla el backend entero, cada lectura lo dice y ninguna se vuelve vacía", async () => {
  const down = failing(FAILURES["conexión rechazada"]);
  const reads = await readDashboard(
    fakeSource({
      listProducts: down,
      listAgents: down,
      listAgentExecutions: down,
      listApprovals: down,
      listPipelineReviews: down,
    }).source,
  );

  for (const state of [reads.products, reads.agents, reads.executions, reads.approvals, reads.reviews]) {
    assert.equal(state.kind, "error");
  }
  assert.deepEqual(reads.catalog, []);
});
