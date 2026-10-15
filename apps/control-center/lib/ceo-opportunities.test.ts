import assert from "node:assert/strict";
import { test } from "node:test";
import { failed, loaded, product } from "./ceo-block-test-support.ts";
import { CANDIDATES_BLOCK, CANDIDATES_FOOTNOTE, candidatesBlock } from "./ceo-opportunities.ts";
import type { BlockView } from "./ceo-block-view.ts";

// CANDIDATOS DETECTADOS (M47, Commit 3B, D-3B-2). El backend NO tiene una entidad «oportunidad validada»: solo el candidato
// (`products`, estado CANDIDATE). Por eso el bloque se llama «Candidatos detectados», cada fila dice «Candidato · sin validar» y
// ninguna palabra afirma que algo esté validado, confirmado o sea una oportunidad. El título «Oportunidades detectadas» volverá
// cuando exista una entidad real que lo sostenga.

const view = (products = loaded([product("p1")])): BlockView => candidatesBlock({ products });
const rowsOf = (v: BlockView) => (v.kind === "loaded" ? v.rows : []);

test("el bloque se llama «Candidatos detectados», NO «Oportunidades detectadas», y enlaza a Investigación", () => {
  assert.equal(CANDIDATES_BLOCK.title, "Candidatos detectados");
  assert.doesNotMatch(CANDIDATES_BLOCK.title, /Oportunidades detectadas/);
  assert.equal(CANDIDATES_BLOCK.seeAll.href, "/research");
  assert.equal(CANDIDATES_BLOCK.seeAll.label, "Ver todos");
});

test("cada candidato es una fila con su nombre real, su categoría, su origen y la etiqueta «Candidato · sin validar»", () => {
  const v = view(loaded([product("p1", { name: "Freidora de aire", category: "cocina", source: "research" }), product("p2", { name: "Soporte", category: "oficina", source: "manual" })]));
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 2);
  assert.equal(v.countText, "2 candidatos");
  assert.deepEqual(v.rows.map((r) => [r.title, r.subtitle, r.tag.text]), [
    ["Freidora de aire", "cocina · Investigación", "Candidato · sin validar"],
    ["Soporte", "oficina · Manual", "Candidato · sin validar"],
  ]);
});

test("un solo candidato dice «1 candidato» (singular)", () => {
  const v = view();
  assert.equal(v.kind === "loaded" && v.countText, "1 candidato");
});

test("ningún candidato aparece como «Oportunidad», «Validada» o «Confirmada» (ni cualquier cosa que lo insinúe)", () => {
  const v = view(loaded([product("p1"), product("p2", { source: "manual" })]));
  if (v.kind !== "loaded") throw new Error("debería estar cargado");
  const sinPie = JSON.stringify({ ...v, footnote: null });
  assert.doesNotMatch(sinPie, /oportunidad|validad[ao]s?\b|confirmad[ao]s?|score|puntuaci|demanda|tendencia|prioridad|severidad|confianza|nuevo mercado/i);
  assert.doesNotMatch(CANDIDATES_BLOCK.title + CANDIDATES_BLOCK.tab, /oportunidad/i);
});

test("la única mención a las oportunidades es la línea secundaria fija: «Oportunidades validadas: no disponibles»", () => {
  assert.equal(CANDIDATES_FOOTNOTE, "Oportunidades validadas: no disponibles");
  const v = view();
  assert.equal(v.kind === "loaded" && v.footnote, CANDIDATES_FOOTNOTE);
  const vacio = view({ kind: "empty" });
  assert.equal(vacio.kind === "empty" && vacio.footnote, CANDIDATES_FOOTNOTE);
});

test("lo que NO existe no se muestra: ni score, ni prioridad, ni severidad, ni confianza, ni fecha", () => {
  const v = view(loaded([product("p1")]));
  if (v.kind !== "loaded") throw new Error("debería estar cargado");
  assert.deepEqual(Object.keys(v.rows[0]).sort(), ["detail", "key", "provenance", "subtitle", "tag", "title"]);
  assert.equal(v.rows[0].tag.level, undefined);
  assert.equal(v.rows[0].provenance.confidence, null);
  assert.equal(v.rows[0].provenance.at, null);
  assert.equal(v.rows[0].provenance.rationale, null);
});

test("tres visibles y «N más»: 9 candidatos", () => {
  const nine = Array.from({ length: 9 }, (_, i) => product(`p${i}`));
  const v = view(loaded(nine));
  assert.equal(v.kind, "loaded");
  if (v.kind !== "loaded") return;
  assert.equal(v.count, 9);
  assert.equal(v.countText, "9 candidatos");
  assert.equal(v.visible.length, 3);
  assert.equal(v.more, 6);
});

test("se respeta el orden del backend (sin reordenar ni elegir)", () => {
  const v = view(loaded([product("z", { name: "Zeta" }), product("a", { name: "Alfa" })]));
  assert.deepEqual(rowsOf(v).map((r) => r.title), ["Zeta", "Alfa"]);
});

test("procedencia trazable: fuente, entidad, id, estado y origen reales", () => {
  const v = view(loaded([product("p1", { source: "manual", status: "CANDIDATE" })]));
  assert.deepEqual(rowsOf(v)[0].provenance, {
    source: "products",
    entity: "product",
    id: "p1",
    status: "CANDIDATE",
    areaLabel: "Manual",
    at: null,
    confidence: null,
    rationale: null,
  });
});

test("lista vacía válida ⇒ VACÍO; error ⇒ ERROR; sin leer ⇒ SIN LEER (nunca 0 candidatos)", () => {
  const empty = view({ kind: "empty" });
  assert.equal(empty.kind, "empty");
  assert.equal(empty.kind === "empty" && empty.text, "Sin candidatos en el catálogo.");
  assert.deepEqual(view(failed("No se pudo cargar el catálogo.")), { kind: "error", message: "No se pudo cargar el catálogo." });
  assert.equal(view({ kind: "unread", reason: "x" }).kind, "unread");
  assert.doesNotMatch(JSON.stringify(view(failed())), /0 candidatos|Sin candidatos/);
});

test("el resultado no lleva demostración ni señales de mercado", () => {
  const v = view(loaded([product("p1")]));
  assert.doesNotMatch(JSON.stringify(v), /demo|isDemo|signal|señal/i);
});
