import assert from "node:assert/strict";
import { test } from "node:test";
import type { LegalAnalysis } from "./api.ts";
import { certificationsDeclared, legalGate } from "./legal.ts";

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
