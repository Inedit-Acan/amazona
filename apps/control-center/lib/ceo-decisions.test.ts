import assert from "node:assert/strict";
import { test } from "node:test";
import { approval, failed, HOUR, loaded, NOW, review } from "./ceo-block-test-support.ts";
import { DECISIONS_BLOCK, decisionsBlock } from "./ceo-decisions.ts";
import type { BlockView } from "./ceo-block-view.ts";

// DECISIONES PENDIENTES (M47, Commit 3B, D-3B-1). Una decisión «pendiente» es lo que un humano tiene que contestar y desbloquea algo:
// una aprobación PENDING y no vencida, o una autorización de acción (ACTION_GATE) pendiente. Una aprobación vencida y una revisión
// posterior (POST_HOC) NO lo son: se dicen aparte y no suman al contador. Nada de prioridad, severidad, solicitante, fecha de
// solicitud, confianza ni racional inventados.

const view = (input: Partial<Parameters<typeof decisionsBlock>[0]> = {}): BlockView =>
  decisionsBlock({ approvals: loaded([]), reviews: loaded([]), now: NOW, ...input });

const rowsOf = (v: BlockView) => (v.kind === "loaded" ? v.rows : []);

test("el bloque se llama «Decisiones pendientes» y enlaza a Aprobaciones", () => {
  assert.equal(DECISIONS_BLOCK.title, "Decisiones pendientes");
  assert.equal(DECISIONS_BLOCK.seeAll.href, "/approvals");
});

test("una aprobación pendiente y no vencida aparece, con su acción real, su importe y su vencimiento", () => {
  const v = view({ approvals: loaded([approval("a1", { amount: 120, expires_at: "2026-10-16T14:05:00+00:00" })]) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 1);
  assert.equal(v.countText, "1");
  assert.equal(v.countLabel, "1 decisión accionable");
  assert.equal(v.rows[0].title, "Lanzamiento de campaña de marketing");
  assert.match(v.rows[0].subtitle, /120,00/);
  assert.match(v.rows[0].subtitle, /vence/);
  assert.match(v.rows[0].subtitle, /16 oct 2026.*14:05 UTC/);
  assert.equal(v.rows[0].tag.text, "Aprobación del CEO");
});

test("una aprobación resuelta (APPROVED, REJECTED, EXPIRED, CANCELLED) NO aparece: sin pendientes, el bloque está vacío", () => {
  for (const status of ["APPROVED", "REJECTED", "EXPIRED", "CANCELLED"] as const) {
    const v = view({ approvals: loaded([approval("a1", { status, resolved_at: "2026-10-14T00:00:00Z" })]) });
    assert.equal(v.kind, "empty", status);
  }
});

test("una aprobación PENDING VENCIDA no cuenta como accionable: no es fila ni suma; se dice aparte", () => {
  const v = view({ approvals: loaded([approval("a1", { expires_at: new Date(NOW - HOUR).toISOString() })]) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 0);
  assert.deepEqual(v.rows, []);
  assert.equal(v.noRowsText, "Ninguna decisión accionable.");
  assert.deepEqual(v.secondary, ["1 aprobación vencida sin resolver"]);
});

test("el vencimiento exacto ya cuenta como vencida (el backend la rechaza en ese instante)", () => {
  const v = view({ approvals: loaded([approval("a1", { expires_at: new Date(NOW).toISOString() })]) });
  assert.equal(v.kind === "loaded" && v.count, 0);
});

test("una ACTION_GATE pendiente cuenta; una POST_HOC NO cuenta y se dice aparte («no autorizan nada»)", () => {
  const v = view({ reviews: loaded([review("g1"), review("p1", { kind: "POST_HOC", step: null, action: null, reasons: ["costes por encima de lo previsto"] })]) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 1);
  assert.equal(v.rows.length, 1);
  assert.equal(v.rows[0].title, "Autorizar: activar la publicidad");
  assert.equal(v.rows[0].tag.text, "Autorización de acción");
  assert.deepEqual(v.secondary, ["1 revisión posterior sin resolver (no autoriza nada)"]);
});

test("solo hay POST_HOC: contador 0, sin filas, y la revisión posterior dicha aparte", () => {
  const v = view({ reviews: loaded([review("p1", { kind: "POST_HOC", step: null, action: null })]) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 0);
  assert.equal(v.secondary.length, 1);
});

test("una revisión que no está PENDING no aparece", () => {
  const v = view({ reviews: loaded([review("g1", { status: "APPROVED", resolved_at: "2026-10-14T00:00:00Z" })]) });
  assert.equal(v.kind, "empty");
});

test("orden aprobado: aprobaciones por vencimiento ascendente, empate por id; las ACTION_GATE después, en el orden del backend", () => {
  const v = view({
    approvals: loaded([
      approval("c", { expires_at: new Date(NOW + 5 * HOUR).toISOString() }),
      approval("b", { expires_at: new Date(NOW + 2 * HOUR).toISOString() }),
      approval("a", { expires_at: new Date(NOW + 2 * HOUR).toISOString() }),
    ]),
    reviews: loaded([review("g2", { action: "spend_money" }), review("g1", { action: "ship_order" })]),
  });
  assert.deepEqual(
    rowsOf(v).map((r) => r.provenance.id),
    ["a", "b", "c", "g2", "g1"],
  );
});

test("el orden no depende del orden de entrada de las aprobaciones", () => {
  const items = [approval("x", { expires_at: new Date(NOW + 9 * HOUR).toISOString() }), approval("y", { expires_at: new Date(NOW + HOUR).toISOString() })];
  const a = view({ approvals: loaded(items) });
  const b = view({ approvals: loaded([...items].reverse()) });
  assert.deepEqual(rowsOf(a).map((r) => r.provenance.id), rowsOf(b).map((r) => r.provenance.id));
});

test("una aprobación sin vencimiento es accionable y va detrás de las que sí vencen", () => {
  const v = view({ approvals: loaded([approval("n", { expires_at: null }), approval("t", { expires_at: new Date(NOW + HOUR).toISOString() })]) });
  assert.deepEqual(rowsOf(v).map((r) => r.provenance.id), ["t", "n"]);
  assert.match(rowsOf(v)[1].subtitle, /Sin vencimiento/);
});

test("importe: nulo es «Sin importe» (no es 0); el cero real se enseña; sin moneda inventada", () => {
  const nulo = rowsOf(view({ approvals: loaded([approval("a", { amount: null })]) }))[0];
  assert.match(nulo.subtitle, /Sin importe/);
  assert.doesNotMatch(nulo.subtitle, /0,00/);
  const cero = rowsOf(view({ approvals: loaded([approval("a", { amount: 0 })]) }))[0];
  assert.match(cero.subtitle, /Importe 0,00/);
  const grande = rowsOf(view({ approvals: loaded([approval("a", { amount: 2500 })]) }))[0];
  assert.match(grande.subtitle, /2\.500,00/);
  for (const row of [nulo, cero, grande]) assert.doesNotMatch(JSON.stringify(row), /€|EUR|USD/);
});

test("el importe NO deriva ninguna prioridad: ninguna insignia, ningún campo de prioridad o severidad", () => {
  const v = view({ approvals: loaded([approval("a", { amount: 99999 }), approval("b", { amount: 1 })]), reviews: loaded([review("g")]) });
  for (const row of rowsOf(v)) {
    assert.deepEqual(Object.keys(row).sort(), ["detail", "key", "provenance", "subtitle", "tag", "title"]);
    assert.equal(row.tag.level, undefined);
    assert.doesNotMatch(JSON.stringify(row), /prioridad|priority|severity|severidad|\b(Alta|Media|Baja|Crítica)\b/i);
  }
});

test("confidence, rationale y solicitante NO se inventan: la confianza es nula y el racional solo existe si hay motivos reales", () => {
  const v = view({ approvals: loaded([approval("a")]), reviews: loaded([review("g", { reasons: ["motivo uno", "motivo dos"] }), review("g2", { reasons: [] })]) });
  const [a, g, g2] = rowsOf(v);
  assert.equal(a.provenance.confidence, null);
  assert.equal(a.provenance.rationale, null);
  assert.equal(g.provenance.confidence, null);
  assert.equal(g.provenance.rationale, "motivo uno; motivo dos");
  assert.equal(g2.provenance.rationale, null);
  assert.doesNotMatch(JSON.stringify(v), /confianza|racional|solicitad[oa] por|requested_by|opportunity_score/i);
});

test("una recomendación (Decision) NO se convierte en decisión pendiente: el bloque solo lee aprobaciones y revisiones", () => {
  // La vista solo recibe aprobaciones, revisiones y «ahora»: una `Decision` (HUMAN_APPROVAL, GO…) no tiene por dónde entrar.
  // Los campos de una recomendación que acompañen a una fila no se arrastran al bloque.
  const noisy = { ...approval("a"), opportunity_score: 0.91, confidence: 0.8, rationale: "el motor recomienda esto", status_decision: "HUMAN_APPROVAL" };
  const v = view({ approvals: loaded([noisy]) });
  assert.doesNotMatch(JSON.stringify(v), /0\.91|0\.8|el motor recomienda|HUMAN_APPROVAL|opportunity_score/);
});

test("la procedencia de cada fila es trazable: fuente, entidad, id, estado, área y marca de tiempo reales", () => {
  const v = view({ approvals: loaded([approval("a1", { expires_at: "2026-10-16T14:05:00+00:00" })]), reviews: loaded([review("g1")]) });
  const [a, g] = rowsOf(v);
  assert.deepEqual(a.provenance, {
    source: "approvals",
    entity: "approval",
    id: "a1",
    status: "PENDING",
    areaLabel: "Aprobación del CEO",
    at: "2026-10-16T14:05:00+00:00",
    requestedAt: null,
    correlationId: null,
    confidence: null,
    rationale: null,
  });
  assert.equal(g.provenance.source, "pipeline_reviews");
  assert.equal(g.provenance.entity, "pipeline_review");
  assert.equal(g.provenance.id, "g1");
  assert.equal(g.provenance.at, null);
});

test("la acción de una ACTION_GATE sin acción conocida no se inventa: se usa el nombre real o un texto neutro", () => {
  const raw = rowsOf(view({ reviews: loaded([review("g", { action: "algo_nuevo" })]) }))[0];
  assert.equal(raw.title, "Autorizar: algo_nuevo");
  const none = rowsOf(view({ reviews: loaded([review("g", { action: null, step: null })]) }))[0];
  assert.equal(none.title, "Autorización de acción");
  assert.match(none.subtitle, /Paso no indicado/);
});

test("tres visibles y «N más»", () => {
  const items = ["a", "b", "c", "d", "e"].map((id, i) => approval(id, { expires_at: new Date(NOW + (i + 1) * HOUR).toISOString() }));
  const v = view({ approvals: loaded(items) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 5);
  assert.equal(v.visible.length, 3);
  assert.equal(v.more, 2);
});

test("con las dos lecturas válidas y nada: VACÍO (un hecho), con su texto", () => {
  const v = view();
  assert.deepEqual(v, { kind: "empty", text: "Ninguna decisión pendiente.", footnote: null });
});

test("ERROR ≠ VACÍO: si falla cualquiera de las dos lecturas, el bloque entero es error, sin recuento parcial", () => {
  const withRows = { approvals: loaded([approval("a1")]), reviews: loaded([review("g1")]) };
  for (const broken of [{ approvals: failed("No se pudieron cargar las aprobaciones.") }, { reviews: failed("No se pudieron cargar las revisiones de pipeline.") }]) {
    const v = view({ ...withRows, ...broken });
    assert.equal(v.kind, "error");
    assert.doesNotMatch(JSON.stringify(v), /Lanzamiento|Autorizar|"count"|"rows"/);
  }
  const both = view({ approvals: failed("No se pudieron cargar las aprobaciones."), reviews: failed("No se pudieron cargar las revisiones de pipeline.") });
  assert.equal(both.kind === "error" && /aprobaciones/.test(both.message) && /revisiones/.test(both.message), true);
});

test("UNREAD ≠ VACÍO: una lectura no hecha da «sin leer», nunca vacío ni 0", () => {
  const v = view({ approvals: { kind: "unread", reason: "No se ha leído." } });
  assert.equal(v.kind, "unread");
  assert.doesNotMatch(JSON.stringify(v), /Ninguna decisión|"count"/);
  // `error` gana a `unread`.
  assert.equal(view({ approvals: { kind: "unread", reason: "x" }, reviews: failed() }).kind, "error");
});

test("el resultado no lleva demostración: ningún texto de demo, ningún `isDemo`", () => {
  const v = view({ approvals: loaded([approval("a")]), reviews: loaded([review("g")]) });
  assert.doesNotMatch(JSON.stringify(v), /demo|isDemo|APR-\d|ACT-|REV-/i);
});

// --- Commit 6b: «Solicitada <fecha UTC>» con `requested_at` REAL, y la correlación para poder rastrear -----------------------------------------

test("6b · con `requested_at` la fila dice «Solicitada <fecha y hora UTC>» (la fecha del backend, no la caducidad ni «ahora»)", () => {
  const v = view({
    approvals: loaded([approval("a1", { requested_at: "2026-10-16T09:30:00+02:00", expires_at: "2026-10-17T07:30:00Z" })]),
  });
  const row = rowsOf(v)[0];
  assert.equal(row.meta, "Solicitada 16 oct 2026 · 07:30 UTC");
  assert.doesNotMatch(row.meta ?? "", /17 oct/, "no es la caducidad");
  assert.equal(row.provenance.requestedAt, "2026-10-16T09:30:00+02:00");
});

test("6b · SIN `requested_at` (backend anterior al 6a) no se enseña ninguna fecha de solicitud: ni «ahora», ni caducidad − 24 h", () => {
  const v = view({ approvals: loaded([approval("a1", { expires_at: "2026-10-17T07:30:00Z" })]) });
  const row = rowsOf(v)[0];
  assert.equal(row.meta, undefined);
  assert.equal(row.provenance.requestedAt ?? null, null);
  assert.doesNotMatch(JSON.stringify(row), /Solicitada|16 oct/);
});

test("6b · el `correlation_id` se conserva en la procedencia y se ofrece como línea de trazabilidad; sin él no se inventa", () => {
  const corr = "0f8e2c1a-7b3d-4c5e-9a10-2b4d6f8a0c1e";
  const withIt = rowsOf(view({ approvals: loaded([approval("a1", { correlation_id: corr })]) }))[0];
  assert.equal(withIt.provenance.correlationId, corr);
  assert.ok(withIt.detail.includes(`Correlación: ${corr}`));
  const without = rowsOf(view({ approvals: loaded([approval("a2")]) }))[0];
  assert.equal(without.provenance.correlationId ?? null, null);
  assert.ok(!without.detail.some((line) => line.startsWith("Correlación")));
});

test("6b · la fecha de solicitud no cambia el orden (sigue por vencimiento) ni el contador, y las revisiones de pipeline no la tienen", () => {
  const v = view({
    approvals: loaded([
      approval("late", { expires_at: "2026-10-17T18:00:00Z", requested_at: "2026-10-16T01:00:00Z" }),
      approval("early", { expires_at: "2026-10-16T18:00:00Z", requested_at: "2026-10-16T11:00:00Z" }),
    ]),
    reviews: loaded([review("g1")]),
  });
  assert.deepEqual(rowsOf(v).map((r) => r.key), ["approval:early", "approval:late", "review:g1"]);
  assert.equal(rowsOf(v)[2].meta, undefined, "una revisión de pipeline no trae fecha de solicitud");
});
