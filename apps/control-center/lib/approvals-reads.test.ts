import assert from "node:assert/strict";
import { test } from "node:test";
import { readApprovalsPage, PRODUCT_LIMIT, type ApprovalsSource } from "./approvals-reads.ts";
import { approval, product, review } from "./ceo-block-test-support.ts";
import { FAILURES, INVALID_PAYLOADS, LOOKS_LIKE_ABSENCE, TECHNICAL, agent } from "./read-test-support.ts";

// Las lecturas de /approvals (M47, Commit 6b). Antes había 8 `.catch(() => [])`: un fallo de las revisiones, del registro de agentes, del
// catálogo o de cualquier análisis se veía como «no hay nada». Ahora cada lectura es un `ReadState` y el contexto de la demostración
// dice qué no pudo leer.

const reject = (make: () => Error) => async (): Promise<never> => {
  throw make();
};

function fakeSource(over: Partial<ApprovalsSource> = {}): ApprovalsSource & { calls: Record<string, number> } {
  const calls: Record<string, number> = {};
  const counted =
    <T>(name: string, value: (...args: string[]) => Promise<T>) =>
    (...args: string[]) => {
      calls[name] = (calls[name] ?? 0) + 1;
      return value(...args);
    };
  return {
    calls,
    listApprovals: counted("listApprovals", over.listApprovals ?? (async () => [])),
    listPipelineReviews: counted("listPipelineReviews", over.listPipelineReviews ?? (async () => [])),
    listAgents: counted("listAgents", over.listAgents ?? (async () => [])),
    listProducts: counted("listProducts", over.listProducts ?? (async () => [])),
    listProductSuppliers: counted("listProductSuppliers", over.listProductSuppliers ?? (async () => [])),
    listProductEconomics: counted("listProductEconomics", over.listProductEconomics ?? (async () => [])),
    listProductLegal: counted("listProductLegal", over.listProductLegal ?? (async () => [])),
    listProductStorefronts: counted("listProductStorefronts", over.listProductStorefronts ?? (async () => [])),
    listProductCampaigns: counted("listProductCampaigns", over.listProductCampaigns ?? (async () => [])),
  };
}

test("una ronda: cada lectura una vez, y por producto las cinco de su contexto (con el tope de productos)", async () => {
  const products = Array.from({ length: 9 }, (_unused, i) => product(`p${i}`));
  const source = fakeSource({ listProducts: async () => products });
  const reads = await readApprovalsPage(source);
  assert.equal(PRODUCT_LIMIT, 6);
  assert.equal(source.calls.listApprovals, 1);
  assert.equal(source.calls.listPipelineReviews, 1);
  assert.equal(source.calls.listAgents, 1);
  assert.equal(source.calls.listProducts, 1);
  for (const name of ["listProductSuppliers", "listProductEconomics", "listProductLegal", "listProductStorefronts", "listProductCampaigns"]) {
    assert.equal(source.calls[name], 6, name);
  }
  assert.equal(reads.contexts.length, 6);
  assert.deepEqual(reads.contextFailures, []);
});

test("con datos: aprobaciones y revisiones cargadas con su contrato", async () => {
  const reads = await readApprovalsPage(fakeSource({ listApprovals: async () => [approval("a1")], listPipelineReviews: async () => [review("g1")] }));
  assert.equal(reads.approvals.kind, "loaded");
  assert.equal(reads.reviews.kind, "loaded");
});

test("vacío válido ⇒ `empty` (un hecho) en cada fuente", async () => {
  const reads = await readApprovalsPage(fakeSource());
  assert.deepEqual([reads.approvals.kind, reads.reviews.kind, reads.agents.kind, reads.products.kind], ["empty", "empty", "empty", "empty"]);
});

test("un fallo de aprobaciones o de revisiones es `error` de ESA fuente (mensaje nuestro, sin nada técnico, que no parece una ausencia)", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const a = await readApprovalsPage(fakeSource({ listApprovals: reject(make), listPipelineReviews: async () => [review("g1")] }));
    assert.deepEqual([a.approvals.kind, a.reviews.kind], ["error", "loaded"], name);
    const r = await readApprovalsPage(fakeSource({ listPipelineReviews: reject(make), listApprovals: async () => [approval("a1")] }));
    assert.deepEqual([r.approvals.kind, r.reviews.kind], ["loaded", "error"], name);
    for (const state of [a.approvals, r.reviews]) {
      assert.equal(state.kind, "error");
      if (state.kind !== "error") continue;
      assert.doesNotMatch(state.message, TECHNICAL, `${name}: ${state.message}`);
      assert.doesNotMatch(state.message, LOOKS_LIKE_ABSENCE, name);
    }
  }
});

test("una respuesta con la forma equivocada es error, no vacío", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const reads = await readApprovalsPage(fakeSource({ listApprovals: async () => payload as never, listPipelineReviews: async () => payload as never }));
    assert.deepEqual([reads.approvals.kind, reads.reviews.kind], ["error", "error"], name);
  }
});

test("una aprobación con un estado desconocido o una fecha de solicitud rota rompe el contrato (error), no se descarta la fila", async () => {
  const unknown = await readApprovalsPage(fakeSource({ listApprovals: async () => [approval("a1", { status: "PAUSED" as never })] }));
  assert.equal(unknown.approvals.kind, "error");
  const brokenDate = await readApprovalsPage(fakeSource({ listApprovals: async () => [approval("a1", { requested_at: "ayer" })] }));
  assert.equal(brokenDate.approvals.kind, "error");
});

test("el registro de agentes o el catálogo que fallan NO se vuelven `[]`: son `error`, y se dice qué contexto de la demostración falta", async () => {
  const reads = await readApprovalsPage(fakeSource({ listAgents: reject(FAILURES["500"]), listProducts: reject(FAILURES["503"]) }));
  assert.equal(reads.agents.kind, "error");
  assert.equal(reads.products.kind, "error");
  assert.deepEqual(reads.contextFailures, ["el registro de agentes", "el catálogo de productos"]);
  assert.deepEqual(reads.contexts, []);
});

test("un análisis de un producto que falla se anota (producto y fuente); el resto del contexto se conserva", async () => {
  const reads = await readApprovalsPage(
    fakeSource({
      listProducts: async () => [product("p1", { name: "Organizador" })],
      listProductLegal: reject(FAILURES["500"]),
      listProductEconomics: async () => [],
    }),
  );
  assert.equal(reads.contexts.length, 1);
  assert.deepEqual(reads.contextFailures, ["los análisis legales de «Organizador»"]);
});

test("un fallo de aprobaciones NO apaga las lecturas del contexto de la demostración, ni al revés", async () => {
  const reads = await readApprovalsPage(fakeSource({ listApprovals: reject(FAILURES["500"]), listAgents: async () => [agent("agent-1")], listProducts: async () => [product("p1")] }));
  assert.equal(reads.approvals.kind, "error");
  assert.equal(reads.agents.kind, "loaded");
  assert.equal(reads.contexts.length, 1);
});

test("la lectura no lleva ventana ni periodo: el selector 7/14/30 no existe aquí", () => {
  assert.equal(readApprovalsPage.length, 1);
});
