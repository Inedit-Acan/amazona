import assert from "node:assert/strict";
import { test } from "node:test";
import { readActivity } from "./ceo-activity-reads.ts";
import { auditAscending, entry, execution, fakeSource, NOW, REGISTRY } from "./ceo-activity-test-support.ts";
import { FAILURES, INVALID_PAYLOADS, LOOKS_LIKE_ABSENCE, TECHNICAL } from "./read-test-support.ts";

// Las lecturas de «Actividad registrada» y «Ejecuciones por área» (M47, Commit 5): TRES peticiones, cada una UNA vez, sin ventana
// temporal; un fallo o un contrato roto es `error` del bloque que lo sufre y no apaga al otro. Nunca `[]`, nunca demostración.

const reject = (make: () => Error) => async (): Promise<never> => {
  throw make();
};

test("UNA sola ronda: cada una de las tres lecturas se hace exactamente una vez", async () => {
  const source = fakeSource();
  await readActivity(source);
  assert.deepEqual(source.calls, { listAudit: 1, listAgents: 1, listAgentExecutions: 1 });
});

test("el selector 7/14/30 no existe para estos bloques: `readActivity` recibe solo la fuente, y el resultado no depende de nada más", async () => {
  assert.equal(readActivity.length, 1, "readActivity(source): sin ventana, sin días, sin instante");
  const make = () => fakeSource({ listAudit: async () => auditAscending(3), listAgentExecutions: async () => [execution("e1", "agent-product-1")] });
  assert.deepEqual(await readActivity(make()), await readActivity(make()));
});

test("la auditoría se pide SIN filtro: ninguna llamada pasa un `correlation_id`", async () => {
  let args: unknown[] = ["no llamada"];
  await readActivity(
    fakeSource({
      listAudit: (async (...received: unknown[]) => {
        args = received;
        return [];
      }) as never,
    }),
  );
  assert.deepEqual(args, []);
});

test("con datos, los dos bloques se cargan cada uno con SU fuente", async () => {
  const { activity, areas } = await readActivity(
    fakeSource({
      listAudit: async () => auditAscending(27, () => ({ actor: "agent-product-1" })),
      listAgentExecutions: async () => [execution("e1", "agent-product-1"), execution("e2", "agent-cfo-1", { success: false })],
    }),
  );
  assert.equal(activity.kind === "loaded" && activity.total, 27);
  assert.equal(areas.kind === "loaded" && areas.total, 2);
});

test("500 filas de auditoría ⇒ la actividad no está disponible, pero las ejecuciones se leen igual", async () => {
  const { activity, areas } = await readActivity(fakeSource({ listAudit: async () => auditAscending(500), listAgentExecutions: async () => [execution("e1", "agent-product-1")] }));
  assert.equal(activity.kind, "unavailable");
  assert.equal(areas.kind, "loaded");
});

test("todo vacío ⇒ los dos bloques están VACÍOS (un hecho)", async () => {
  const { activity, areas } = await readActivity(fakeSource());
  assert.deepEqual([activity.kind, areas.kind], ["empty", "empty"]);
});

test("una lectura que falla rompe SOLO el bloque que la usa, con un texto nuestro y nada técnico", async () => {
  for (const [name, make] of Object.entries(FAILURES)) {
    const audit = await readActivity(fakeSource({ listAudit: reject(make), listAgentExecutions: async () => [execution("e1", "agent-product-1")] }));
    assert.deepEqual([audit.activity.kind, audit.areas.kind], ["error", "loaded"], `${name}: un fallo de auditoría no apaga las ejecuciones`);

    const log = await readActivity(fakeSource({ listAudit: async () => auditAscending(3), listAgentExecutions: reject(make) }));
    assert.deepEqual([log.activity.kind, log.areas.kind], ["loaded", "error"], `${name}: un fallo del log no apaga la actividad`);

    const registry = await readActivity(fakeSource({ listAudit: async () => auditAscending(3), listAgents: reject(make), listAgentExecutions: async () => [execution("e1", "agent-product-1")] }));
    assert.deepEqual([registry.activity.kind, registry.areas.kind], ["loaded", "error"], `${name}: sin registro, la actividad sigue y las áreas son error`);
    assert.equal(registry.activity.kind === "loaded" && registry.activity.agentsNote !== null, true);

    for (const view of [audit.activity, log.areas, registry.areas]) {
      assert.equal(view.kind, "error");
      if (view.kind !== "error") continue;
      assert.doesNotMatch(view.message, TECHNICAL, `${name}: ${view.message}`);
      assert.doesNotMatch(view.message, LOOKS_LIKE_ABSENCE, `${name}: un fallo no se parece a una ausencia`);
    }
  }
});

test("una respuesta con la forma equivocada es error, no vacío", async () => {
  for (const [name, payload] of INVALID_PAYLOADS) {
    const out = await readActivity(fakeSource({ listAudit: async () => payload as never, listAgentExecutions: async () => payload as never, listAgents: async () => payload as never }));
    assert.deepEqual([out.activity.kind, out.areas.kind], ["error", "error"], name);
  }
});

test("una fila de auditoría con `created_at` roto ⇒ error de la actividad (no se omite la fila)", async () => {
  const rows = [...auditAscending(3), entry("zzz", { created_at: "ayer por la tarde" })];
  const out = await readActivity(fakeSource({ listAudit: async () => rows }));
  assert.equal(out.activity.kind, "error");
  assert.equal(out.areas.kind, "empty");
});

test("una fila de ejecución rota ⇒ error de las áreas y la actividad sigue", async () => {
  const rows = [execution("e1", "agent-product-1"), execution("e2", "agent-product-1", { duration_ms: "mucho" as never })];
  const out = await readActivity(fakeSource({ listAudit: async () => auditAscending(2), listAgentExecutions: async () => rows }));
  assert.deepEqual([out.activity.kind, out.areas.kind], ["loaded", "error"]);
});

test("un agente del registro con la forma rota ⇒ las áreas son error y la actividad no se apoya en un registro roto", async () => {
  const broken = [{ ...REGISTRY[0], role: null }] as never;
  const out = await readActivity(fakeSource({ listAudit: async () => [entry("a1", { actor: "agent-product-1" })], listAgents: async () => broken, listAgentExecutions: async () => [execution("e1", "agent-product-1")] }));
  assert.equal(out.areas.kind, "error");
  assert.equal(out.activity.kind === "loaded" && out.activity.visible[0].area, null);
  assert.equal(NOW > 0, true);
});
