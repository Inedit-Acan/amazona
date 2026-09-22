import assert from "node:assert/strict";
import { test } from "node:test";
import type { LegalAnalysis } from "./api.ts";
import { DEMO_REQUIREMENTS, translateLegal } from "./demo/legal.ts";
import { buildLegalView, riskLevel } from "./legal-view.ts";

const analysis = (over: Partial<LegalAnalysis> = {}): LegalAnalysis => ({
  correlation_id: "c1",
  product_id: "p1",
  supplier_quote_id: null,
  market: "eu",
  restricted: false,
  recommendation: "REVIEW",
  confidence: 0.8,
  data: {
    required_certifications: ["CE", "RoHS"],
    known_risks: ["WEEE take-back obligation for electronic waste"],
    recent_changes: [{ date: "2026-03-15", description: "simulated: EU RoHS scope update for wireless accessories" }],
  },
  ...over,
});

test("riskLevel: probabilidad × impacto", () => {
  assert.equal(riskLevel(3, 4), "Crítico");
  assert.equal(riskLevel(2, 3), "Alto");
  assert.equal(riskLevel(2, 2), "Medio");
  assert.equal(riskLevel(1, 1), "Bajo");
});

test("buildLegalView sin análisis: matriz de ejemplo, cumplimiento y Legal Gate bloqueado por un crítico abierto", () => {
  const v = buildLegalView("eu", undefined);
  assert.equal(v.requirements.length, DEMO_REQUIREMENTS.eu.length);
  assert.equal(v.compliance.ok, 7);
  assert.equal(v.gate.state, "blocked");
  assert.equal(v.gate.criticalOpen, 1);
  assert.equal(v.requirements[0].criticality, "Crítico");
  assert.deepEqual(v.actions, ["Validar marcado CE", "Completar etiquetado e instrucciones", "Aportar manual de usuario (ES)"]);
  assert.equal(v.documents.required, v.documents.verified + v.documents.pending);
  assert.equal(v.risk.level, "Medio");
});

test("buildLegalView: si el agente exige una certificación no declarada, queda pendiente y sin evidencia", () => {
  const v = buildLegalView("eu", analysis());
  const rohs = v.requirements.find((r) => r.name.startsWith("RoHS"))!;
  assert.equal(rohs.fromAgent, true);
  assert.equal(rohs.status, "Pendiente");
  assert.equal(rohs.evidence, 0);
  assert.ok(v.risks.some((r) => r.fromAgent && r.name.includes("WEEE")));
  assert.ok(v.changes.some((c) => c.fromAgent && c.description === "Ampliación del alcance de RoHS a accesorios inalámbricos"));
});

test("buildLegalView: certificaciones del agente que no están en la matriz se añaden como críticas", () => {
  const v = buildLegalView("eu", analysis({ data: { required_certifications: ["XYZ"] } }));
  const extra = v.requirements.find((r) => r.name === "Certificación XYZ")!;
  assert.equal(extra.criticality, "Crítico");
  assert.equal(extra.status, "Pendiente");
});

test("buildLegalView: NO_GO o categoría restringida bloquean el Legal Gate", () => {
  assert.equal(buildLegalView("eu", analysis({ recommendation: "NO_GO" })).gate.state, "blocked");
  const restricted = buildLegalView("eu", analysis({ restricted: true }));
  assert.equal(restricted.gate.state, "blocked");
  assert.equal(restricted.risks[0].name, "Categoría restringida en este mercado");
});

test("translateLegal: traduce el dataset y quita el prefijo «simulated»", () => {
  assert.equal(translateLegal("simulated: EU RoHS scope update for wireless accessories"), "Ampliación del alcance de RoHS a accesorios inalámbricos");
  assert.equal(translateLegal("simulated: something new"), "Something new");
});
