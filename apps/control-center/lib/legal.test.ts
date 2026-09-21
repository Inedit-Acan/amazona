import assert from "node:assert/strict";
import { test } from "node:test";
import type { LegalAnalysis } from "./api.ts";
import {
  certificationsDeclared,
  changesNewestFirst,
  gateReasons,
  legalGate,
  requirementRows,
} from "./legal.ts";

function analysis(overrides: Partial<LegalAnalysis> = {}): LegalAnalysis {
  return {
    correlation_id: "c1",
    product_id: "p1",
    supplier_quote_id: null,
    market: "eu",
    restricted: false,
    recommendation: "REVIEW",
    confidence: 0.85,
    data: { required_certifications: ["CE", "RoHS"] },
    ...overrides,
  };
}

test("legalGate traduce cada recomendación a un estado del Legal Gate y nunca promete 100 % legal", () => {
  assert.equal(legalGate("NO_GO").title, "Bloqueado");
  assert.equal(legalGate("REVIEW").title, "Requiere revisión humana");
  assert.equal(legalGate("GO").title, "Preparado");
  assert.equal(legalGate("NO_GO").tone, "bad");
  assert.equal(legalGate("REVIEW").tone, "warn");
  assert.equal(legalGate("GO").tone, "ok");
  assert.doesNotMatch(legalGate("GO").detail, /100\s?%\s?legal/i);
});

test("certificationsDeclared: solo si se exigen certificaciones y el agente devolvió GO", () => {
  assert.equal(certificationsDeclared(analysis({ recommendation: "GO" })), true);
  assert.equal(certificationsDeclared(analysis({ recommendation: "REVIEW" })), false);
  assert.equal(certificationsDeclared(analysis({ recommendation: "NO_GO" })), false);
  // sin certificaciones exigidas no hay nada que declarar, aunque sea GO
  assert.equal(certificationsDeclared(analysis({ recommendation: "GO", data: { required_certifications: [] } })), false);
  assert.equal(certificationsDeclared(analysis({ recommendation: "GO", data: null })), false);
});

test("requirementRows: una fila por certificación, declarada o pendiente", () => {
  const pending = requirementRows(analysis());
  assert.deepEqual(
    pending.map((r) => [r.name, r.status, r.market]),
    [
      ["CE", "pending", "eu"],
      ["RoHS", "pending", "eu"],
    ],
  );
  const declared = requirementRows(analysis({ recommendation: "GO" }));
  assert.ok(declared.every((r) => r.status === "declared"));
  assert.equal(new Set(declared.map((r) => r.id)).size, 2);
  assert.deepEqual(requirementRows(analysis({ data: null })), []);
});

test("gateReasons: restringida sin certificar, solo restringida, sin datos y sin motivos", () => {
  assert.deepEqual(
    gateReasons(analysis({ restricted: true, recommendation: "NO_GO", data: { required_certifications: ["REACH"] } })),
    ["Categoría restringida en Unión Europea.", "Certificaciones sin acreditar: REACH."],
  );
  assert.deepEqual(gateReasons(analysis({ recommendation: "REVIEW" })), ["Certificaciones sin acreditar: CE, RoHS."]);
  assert.deepEqual(
    gateReasons(analysis({ restricted: true, recommendation: "GO", data: { required_certifications: ["REACH"] } })),
    ["Categoría restringida en Unión Europea."],
  );
  assert.deepEqual(gateReasons(analysis({ recommendation: "GO", data: { required_certifications: [] } })), []);
  const unmodeled = gateReasons(analysis({ restricted: null, data: {} }));
  assert.equal(unmodeled.length, 1);
  assert.match(unmodeled[0], /Sin datos regulatorios/);
});

test("changesNewestFirst ordena por fecha descendente sin mutar la entrada", () => {
  const input = [
    { date: "2026-03-15", description: "a" },
    { date: "2026-06-01", description: "b" },
  ];
  assert.deepEqual(
    changesNewestFirst(input).map((c) => c.description),
    ["b", "a"],
  );
  assert.equal(input[0].description, "a");
  assert.deepEqual(changesNewestFirst(undefined), []);
});
