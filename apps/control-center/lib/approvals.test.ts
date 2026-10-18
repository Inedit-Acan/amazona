import assert from "node:assert/strict";
import { test } from "node:test";
import type { Approval } from "./api.ts";
import { actionLabel, decisionImpact, isActionable, isExpired, resolvedImpact } from "./approvals.ts";

const NOW = new Date("2026-09-22T12:00:00Z");

const approval = (overrides: Partial<Approval> = {}): Approval => ({
  id: "apr-1",
  decision_id: "dec-1",
  action: "launch_marketing_campaign",
  amount: 1500,
  status: "PENDING",
  expires_at: new Date(NOW.getTime() + 3_600_000).toISOString(),
  resolved_at: null,
  resolved_by: null,
  ...overrides,
});

test("isExpired: solo una pendiente con vencimiento pasado está vencida", () => {
  assert.equal(isExpired(approval(), NOW), false);
  assert.equal(isExpired(approval({ expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), true);
  assert.equal(isExpired(approval({ expires_at: null }), NOW), false);
  assert.equal(isExpired(approval({ status: "APPROVED", expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), false);
});

test("isActionable: pendiente y sin vencer", () => {
  assert.equal(isActionable(approval(), NOW), true);
  assert.equal(isActionable(approval({ status: "REJECTED" }), NOW), false);
  assert.equal(isActionable(approval({ expires_at: new Date(NOW.getTime() - 1).toISOString() }), NOW), false);
});

test("actionLabel traduce lo conocido y limpia lo demás", () => {
  assert.equal(actionLabel("launch_marketing_campaign"), "Lanzamiento de campaña de marketing");
  assert.equal(actionLabel("purchase_stock"), "Purchase stock");
});

const ALL_TEXT = (impact: { approve: string[]; reject: string[] }) => [...impact.approve, ...impact.reject].join(" | ");

test("decisionImpact con una reserva real: aprobar compromete lo reservado y rechazar lo libera", () => {
  const impact = decisionImpact({ action: "launch_marketing_campaign", amount: 1500, budget_effect: "reserved" });
  assert.ok(impact.approve[0].includes("1.500"));
  assert.ok(impact.approve.some((line) => /pasa a comprometido/.test(line)));
  assert.ok(impact.reject.some((line) => /Se libera la reserva de .*1\.500/.test(line)));
});

test("decisionImpact SIN reserva (despliegue simulado sin presupuesto): nunca dice reservado ni comprometido como algo que ocurre", () => {
  const impact = decisionImpact({ action: "simulated_external_spend", amount: 1, budget_effect: "none" });
  const text = ALL_TEXT(impact);
  assert.doesNotMatch(text, /pasa de reservado|pasa a comprometido|Se libera la reserva de/);
  assert.ok(impact.approve.some((line) => /no reserva ni compromete fondos/.test(line)));
  assert.ok(impact.reject.some((line) => /No hay reserva que liberar/.test(line)));
});

test("decisionImpact sin el dato del libro (backend anterior): «Impacto financiero no disponible», no se asume presupuesto", () => {
  const impact = decisionImpact({ action: "x", amount: 40 });
  assert.ok(impact.approve.includes("Impacto financiero no disponible."));
  assert.ok(impact.reject.includes("Impacto financiero no disponible."));
  assert.doesNotMatch(ALL_TEXT(impact), /reserv|comprometid/i);
});

test("decisionImpact: importe 0 o ausente no finge ningún impacto financiero, con cualquier efecto", () => {
  for (const amount of [0, null]) {
    for (const effect of [undefined, "none", "reserved", "committed", "released"] as const) {
      const text = ALL_TEXT(decisionImpact({ action: "purchase_stock", amount, budget_effect: effect }));
      assert.doesNotMatch(text, /reserv|comprometid|presupuesto|financiero/i, `${amount}/${effect}`);
    }
  }
});

test("el importe no implica presupuesto: el mismo importe sin reserva y con reserva dicen cosas distintas", () => {
  const none = ALL_TEXT(decisionImpact({ action: "x", amount: 100000, budget_effect: "none" }));
  const reserved = ALL_TEXT(decisionImpact({ action: "x", amount: 100000, budget_effect: "reserved" }));
  assert.notEqual(none, reserved);
});

test("decisionImpact: un efecto ya liquidado en una aprobación que sigue pendiente no afirma nada", () => {
  for (const effect of ["committed", "released"] as const) {
    const impact = decisionImpact({ action: "x", amount: 10, budget_effect: effect });
    assert.ok(impact.approve.includes("Impacto financiero no disponible."), effect);
  }
});

test("resolvedImpact dice, en pasado, solo lo que el libro registró", () => {
  assert.match(resolvedImpact({ action: "x", amount: 150, budget_effect: "committed" })[0], /pasó a comprometida/);
  assert.match(resolvedImpact({ action: "x", amount: 150, budget_effect: "released" })[0], /se liberó/);
  assert.match(resolvedImpact({ action: "x", amount: 150, budget_effect: "reserved" })[0], /sigue reservado.*sin liquidar/);
  assert.match(resolvedImpact({ action: "x", amount: 1, budget_effect: "none" })[0], /No hubo movimiento en el presupuesto/);
  assert.equal(resolvedImpact({ action: "x", amount: 1 })[0], "Impacto financiero no disponible.");
  assert.match(resolvedImpact({ action: "x", amount: 0, budget_effect: "none" })[0], /Sin importe/);
});

test("resolvedImpact sin movimiento: nunca dice reservado ni comprometido como un hecho", () => {
  const text = resolvedImpact({ action: "simulated_external_spend", amount: 1, budget_effect: "none" }).join(" ");
  assert.doesNotMatch(text, /pasó a comprometida|se liberó|sigue reservado/);
});
