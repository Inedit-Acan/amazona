import assert from "node:assert/strict";
import { test } from "node:test";
import type { LegalAnalysis, RegulatoryRequirement } from "./api.ts";
import {
  EMPTY_EVIDENCE,
  EMPTY_REQUIREMENT,
  analysisHeadline,
  complianceLabel,
  evidencePayload,
  evidenceProblems,
  existenceLabel,
  existenceNote,
  isRealAnalysis,
  provenanceLabel,
  requirementPayload,
  requirementProblems,
  requirementsFor,
  sourceDatesLine,
  statusInfo,
} from "./regulatory-requirements.ts";

function analysis(data: LegalAnalysis["data"], overrides: Partial<LegalAnalysis> = {}): LegalAnalysis {
  return {
    correlation_id: "c1",
    product_id: "p1",
    supplier_quote_id: null,
    market: "eu",
    restricted: null,
    recommendation: "REVIEW",
    confidence: 0.6,
    data,
    ...overrides,
  };
}

test("solo un análisis con legal_status es real; el simulado no lo lleva", () => {
  assert.equal(isRealAnalysis(analysis({ legal_status: "PASS" })), true);
  assert.equal(isRealAnalysis(analysis({ required_certifications: ["CE"] })), false);
  assert.equal(isRealAnalysis(analysis(null)), false);
  assert.equal(isRealAnalysis(undefined), false);
});

test("PASS dice exactamente lo que significa y nunca «legal» como afirmación", () => {
  const info = statusInfo("PASS");
  assert.equal(info.tone, "ok");
  assert.match(info.detail, /no ha encontrado un bloqueo/);
  assert.match(info.detail, /No es una garantía de que el producto sea legal/);
  assert.doesNotMatch(info.title, /legal|cumpl|100/i);
});

test("UNKNOWN aclara que la ausencia de requisitos declarados no es ausencia de requisitos", () => {
  const info = statusInfo("UNKNOWN");
  assert.equal(info.tone, "muted");
  assert.match(info.detail, /no significa que no haya requisitos/);
});

test("cada estado tiene su tono y REVIEW_REQUIRED y BLOCKED no se confunden", () => {
  assert.equal(statusInfo("REVIEW_REQUIRED").tone, "warn");
  assert.equal(statusInfo("BLOCKED").tone, "bad");
  assert.notEqual(statusInfo("BLOCKED").title, statusInfo("REVIEW_REQUIRED").title);
});

test("una comprobación vencida se explica como política nuestra, no como norma derogada", () => {
  assert.match(existenceNote("stale") ?? "", /No significa que la norma haya dejado de estar en vigor/);
  assert.match(existenceNote("never_checked") ?? "", /Nadie ha preguntado/);
  assert.equal(existenceNote("verified_in_force"), null);
});

test("las etiquetas de existencia y de evidencia son distintas entre sí", () => {
  assert.equal(existenceLabel("verified_in_force"), "En vigor según la fuente");
  assert.equal(existenceLabel("never_checked"), "Nunca comprobada");
  assert.equal(complianceLabel("none"), "Sin evidencia");
  assert.equal(complianceLabel("third_party_verified"), "Evidencia de un tercero");
});

test("la procedencia se etiqueta por quién sostiene el hecho", () => {
  assert.equal(provenanceLabel("declared"), "Declarado por una persona");
  assert.equal(provenanceLabel("third_party_verified"), "Verificado por un tercero");
});

test("la cabecera de un análisis real no dice «favorable» y avisa de que el techo no está calibrado", () => {
  const line = analysisHeadline(analysis({ legal_status: "PASS" }, { recommendation: "GO" }), "UE");
  assert.doesNotMatch(line, /favorable/);
  assert.match(line, /techo de confianza 60 %/);
  assert.match(line, /no calibrada/);
});

test("la cabecera de un análisis simulado sigue diciendo que es simulado", () => {
  const line = analysisHeadline(analysis({ required_certifications: [] }, { recommendation: "GO" }), "UE");
  assert.match(line, /simulado/);
});

test("sin análisis se dice que no lo hay", () => {
  assert.equal(analysisHeadline(undefined, "UE"), "Sin análisis en UE");
});

test("las fechas de la fuente se enseñan tal cual, varias, y sin interpretar", () => {
  assert.equal(
    sourceDatesLine(["2014-04-18", "2016-04-20"], "9999-12-31"),
    "Fechas de la fuente, sin interpretar — desde: 2014-04-18 · 2016-04-20; hasta: 9999-12-31",
  );
  assert.match(sourceDatesLine(null, null), /desde: sin fecha; hasta: sin dato/);
});

test("el alta exige alcance, CELEX con forma válida, norma y requisito", () => {
  const fields = requirementProblems(EMPTY_REQUIREMENT).map((p) => p.field);
  assert.deepEqual(fields, ["productScope", "celex", "regulation", "requirement"]);
  const ok = {
    ...EMPTY_REQUIREMENT,
    productScope: "Toys",
    celex: "32023R0988",
    regulation: "GPSR",
    requirement: "Safety assessment",
  };
  assert.deepEqual(requirementProblems(ok), []);
  assert.equal(requirementProblems({ ...ok, celex: "hello" }).length, 1);
});

test("el payload declara siempre la aplicabilidad como «declared» y solo para la UE", () => {
  const payload = requirementPayload({
    ...EMPTY_REQUIREMENT,
    productScope: " Toys ",
    celex: " 32023r0988 ",
    regulation: "GPSR",
    requirement: "Safety assessment",
  });
  assert.equal(payload.jurisdiction, "eu");
  assert.equal(payload.applicability_provenance, "declared");
  assert.equal(payload.product_scope, "Toys");
  assert.equal(payload.celex, "32023R0988");
  assert.equal(payload.transposition_reference, null);
  assert.equal(payload.transposition_provenance, null);
});

test("una transposición nacional escrita viaja con su procedencia declarada", () => {
  const payload = requirementPayload({
    ...EMPTY_REQUIREMENT,
    productScope: "Toys",
    celex: "32014L0035",
    regulation: "LVD",
    requirement: "x",
    transposition: "Real Decreto 187/2016",
  });
  assert.equal(payload.transposition_reference, "Real Decreto 187/2016");
  assert.equal(payload.transposition_provenance, "declared");
});

test("la evidencia de un tercero exige emisor, la declarada no", () => {
  assert.deepEqual(evidenceProblems(EMPTY_EVIDENCE), []);
  assert.equal(evidenceProblems({ ...EMPTY_EVIDENCE, provenance: "third_party_verified" }).length, 1);
  assert.deepEqual(
    evidenceProblems({ ...EMPTY_EVIDENCE, provenance: "third_party_verified", issuer: "Organismo 0123" }),
    [],
  );
});

test("el payload de evidencia manda nulos, no cadenas vacías, para lo que no se escribió", () => {
  assert.deepEqual(evidencePayload("r1", EMPTY_EVIDENCE), {
    requirement_id: "r1",
    provenance: "declared",
    source: null,
    reference: null,
    valid_until: null,
  });
});

test("los requisitos de un alcance se emparejan exactos y no por parecido", () => {
  const base = { id: "1", product_scope: "Toys", celex: "32023R0988" } as RegulatoryRequirement;
  const list = [
    base,
    { ...base, id: "2", product_scope: "  toys " },
    { ...base, id: "3", product_scope: "Toy" },
    { ...base, id: "4", product_scope: "Toys and games" },
  ];
  assert.deepEqual(
    requirementsFor(list, "TOYS").map((r) => r.id),
    ["1", "2"],
  );
});
