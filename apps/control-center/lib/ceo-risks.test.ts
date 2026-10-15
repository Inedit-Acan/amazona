import assert from "node:assert/strict";
import { test } from "node:test";
import { failed, HOUR, incident, killSwitch, loaded, NOW, one } from "./ceo-block-test-support.ts";
import { INCIDENTS_BLOCK, incidentsBlock, SEVERITY_LABEL } from "./ceo-risks.ts";
import type { BlockView } from "./ceo-block-view.ts";

// INCIDENCIAS ACTIVAS (M47, Commit 3B, D-3B-3). Hoy NO hay un modelo de riesgo empresarial: solo incidencias abiertas (con
// severidad real LOW/MEDIUM/HIGH/CRITICAL) y el estado del kill switch. Por eso el bloque se llama «Incidencias activas», nunca
// «Riesgos activos». Un kill switch con `enabled === false` es una franja aparte («pipeline detenido»): NO cuenta como incidencia y
// NO lleva severidad. `enabled === true` es lo normal y no se muestra.

const view = (input: Partial<Parameters<typeof incidentsBlock>[0]> = {}): BlockView =>
  incidentsBlock({ incidents: loaded([]), killSwitch: one(killSwitch()), ...input });
const rowsOf = (v: BlockView) => (v.kind === "loaded" ? v.rows : []);

test("el bloque se llama «Incidencias activas», NO «Riesgos activos», y enlaza a Estado", () => {
  assert.equal(INCIDENTS_BLOCK.title, "Incidencias activas");
  assert.doesNotMatch(INCIDENTS_BLOCK.title + INCIDENTS_BLOCK.tab, /Riesgos/);
  assert.equal(INCIDENTS_BLOCK.seeAll.href, "/status");
});

test("la traducción de la severidad real es la aprobada: LOW→Baja, MEDIUM→Media, HIGH→Alta, CRITICAL→Crítica", () => {
  assert.deepEqual(SEVERITY_LABEL, { LOW: "Baja", MEDIUM: "Media", HIGH: "Alta", CRITICAL: "Crítica" });
  for (const [severity, label] of Object.entries(SEVERITY_LABEL)) {
    const row = rowsOf(view({ incidents: loaded([incident("i1", { severity: severity as never })]) }))[0];
    assert.equal(row.tag.text, label, severity);
    assert.equal(row.tag.level, severity.toLowerCase());
  }
});

test("una incidencia OPEN aparece con su título, su severidad real y su fecha de apertura (UTC)", () => {
  const v = view({ incidents: loaded([incident("i1", { title: "Pagos caídos", severity: "HIGH", created_at: "2026-10-15T09:30:00+00:00", description: "El proveedor no responde" })]) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 1);
  assert.equal(v.rows[0].title, "Pagos caídos");
  assert.equal(v.rows[0].tag.text, "Alta");
  assert.match(v.rows[0].subtitle, /15 oct 2026.*09:30 UTC/);
  assert.deepEqual(v.rows[0].detail.includes("El proveedor no responde"), true);
});

test("una incidencia RESOLVED no aparece", () => {
  const v = view({ incidents: loaded([incident("i1", { status: "RESOLVED", resolved_at: "2026-10-15T10:00:00Z" })]) });
  assert.equal(v.kind, "empty");
});

test("orden aprobado: CRITICAL, HIGH, MEDIUM, LOW; dentro de la severidad, created_at descendente; el id desempata", () => {
  const at = (h: number) => new Date(NOW - h * HOUR).toISOString();
  const v = view({
    incidents: loaded([
      incident("low", { severity: "LOW", created_at: at(1) }),
      incident("med-old", { severity: "MEDIUM", created_at: at(9) }),
      incident("crit", { severity: "CRITICAL", created_at: at(20) }),
      incident("med-new", { severity: "MEDIUM", created_at: at(2) }),
      incident("high-b", { severity: "HIGH", created_at: at(5) }),
      incident("high-a", { severity: "HIGH", created_at: at(5) }),
    ]),
  });
  assert.deepEqual(rowsOf(v).map((r) => r.provenance.id), ["crit", "high-a", "high-b", "med-new", "med-old", "low"]);
});

test("el orden no depende del orden de entrada", () => {
  const items = [incident("a", { severity: "LOW" }), incident("b", { severity: "CRITICAL" }), incident("c", { severity: "HIGH" })];
  const ids = (list: typeof items) => rowsOf(view({ incidents: loaded(list) })).map((r) => r.provenance.id);
  assert.deepEqual(ids(items), ids([...items].reverse()));
});

test("el kill switch en `enabled: false` es una franja aparte: con su motivo, sin severidad, y NO suma al contador", () => {
  const v = view({ killSwitch: one(killSwitch({ enabled: false, reason: "revisión de costes", updated_by: "ops" })) });
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 0);
  assert.equal(v.countText, "0");
  assert.deepEqual(v.rows, []);
  assert.equal(v.noRowsText, "Ninguna incidencia abierta.");
  assert.equal(v.strip?.text, "Pipeline detenido por un operador");
  assert.equal(v.strip?.detail, "Motivo: revisión de costes");
  assert.doesNotMatch(JSON.stringify(v.strip), /Alta|Media|Baja|Crítica|severity|level/);
});

test("el kill switch detenido sin motivo no inventa uno", () => {
  const v = view({ killSwitch: one(killSwitch({ enabled: false, reason: null })) });
  assert.equal(v.kind === "loaded" && v.strip?.detail, null);
});

test("POLARIDAD: `enabled: true` (lo normal, y lo que devuelve el backend sin fila) NO muestra nada", () => {
  const v = view({ killSwitch: one(killSwitch({ enabled: true })) });
  assert.equal(v.kind, "empty");
  const conIncidencia = view({ incidents: loaded([incident("i1")]), killSwitch: one(killSwitch({ enabled: true, reason: "texto residual" })) });
  assert.equal(conIncidencia.kind === "loaded" && conIncidencia.strip, null);
  assert.doesNotMatch(JSON.stringify(conIncidencia), /detenido|residual/);
});

test("incidencias y kill switch conviven: el contador es solo de incidencias", () => {
  const v = view({ incidents: loaded([incident("i1"), incident("i2")]), killSwitch: one(killSwitch({ enabled: false, reason: "x" })) });
  assert.equal(v.kind === "loaded" && v.count, 2);
  assert.equal(v.kind === "loaded" && v.countText, "2");
  assert.equal(v.kind === "loaded" && v.countLabel, "2 incidencias abiertas");
  assert.equal(v.kind === "loaded" && v.strip?.text, "Pipeline detenido por un operador");
});

test("VACÍO: «Ninguna incidencia abierta ni pipeline detenido» y NUNCA «Sin riesgos»", () => {
  const v = view();
  assert.deepEqual(v, { kind: "empty", text: "Ninguna incidencia abierta ni pipeline detenido", footnote: null });
  assert.doesNotMatch(JSON.stringify(v), /sin riesgos/i);
});

test("ERROR ≠ VACÍO: si falla las incidencias O el kill switch, el bloque entero es error, sin filas ni franja parciales", () => {
  const withData = { incidents: loaded([incident("i1")]), killSwitch: one(killSwitch({ enabled: false, reason: "x" })) };
  for (const broken of [{ incidents: failed("No se pudieron cargar las incidencias.") }, { killSwitch: failed("No se pudo cargar el estado del pipeline.") }]) {
    const v = view({ ...withData, ...broken });
    assert.equal(v.kind, "error");
    assert.doesNotMatch(JSON.stringify(v), /Incidencia i1|detenido|"count"|"rows"|"strip"/);
  }
});

test("UNREAD ≠ VACÍO; y `error` gana a `unread`", () => {
  assert.equal(view({ incidents: { kind: "unread", reason: "No se ha leído." } }).kind, "unread");
  assert.equal(view({ incidents: { kind: "unread", reason: "x" }, killSwitch: failed() }).kind, "error");
});

test("un error de lectura no produce incidencias ficticias ni demostración", () => {
  const v = view({ incidents: failed("No se pudieron cargar las incidencias.") });
  assert.doesNotMatch(JSON.stringify(v), /Incidencia [a-z0-9]|demo|"rows"|"count"/i);
});

test("lo que NO es una incidencia no entra: la vista solo recibe incidencias y kill switch (agentes y ejecuciones no tienen por dónde entrar)", () => {
  const noisy = { ...incident("i1"), agent_status: "FAILED", run_status: "PARTIAL" };
  const v = view({ incidents: loaded([noisy]) });
  assert.doesNotMatch(JSON.stringify(v), /FAILED|PARTIAL|BLOCKED|DEGRADED/);
});

test("sin prioridad ni confianza: la confianza es nula; el racional es la descripción real o nulo", () => {
  const [a, b] = rowsOf(view({ incidents: loaded([incident("a", { description: "Algo pasó", severity: "HIGH" }), incident("b", { description: null, severity: "LOW" })]) }));
  assert.equal(a.provenance.confidence, null);
  assert.equal(a.provenance.rationale, "Algo pasó");
  assert.equal(b.provenance.rationale, null);
  assert.deepEqual(Object.keys(a).sort(), ["detail", "key", "provenance", "subtitle", "tag", "title"]);
});

test("procedencia trazable", () => {
  const v = view({ incidents: loaded([incident("i1", { severity: "CRITICAL", created_at: "2026-10-15T09:30:00+00:00", description: "d" })]) });
  assert.deepEqual(rowsOf(v)[0].provenance, {
    source: "incidents",
    entity: "incident",
    id: "i1",
    status: "OPEN",
    areaLabel: "Incidencia",
    at: "2026-10-15T09:30:00+00:00",
    confidence: null,
    rationale: "d",
  });
});

test("tres visibles y «N más»", () => {
  const v = view({ incidents: loaded(["a", "b", "c", "d", "e"].map((id) => incident(id))) });
  assert.equal(v.kind === "loaded" && v.visible.length, 3);
  assert.equal(v.kind === "loaded" && v.more, 2);
});
