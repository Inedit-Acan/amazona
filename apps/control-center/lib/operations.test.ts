import assert from "node:assert/strict";
import { test } from "node:test";
import { stageDurations, stageLabel, ticketTypeLabel } from "./operations.ts";

// Los mismos desplazamientos que genera operations/fulfillment.py para un plazo de 12 días.
const STAGES = [
  { stage: "order_placed", day_offset: 0 },
  { stage: "processing", day_offset: 1 },
  { stage: "shipped", day_offset: 12 },
  { stage: "out_for_delivery", day_offset: 14 },
  { stage: "delivered", day_offset: 15 },
];

test("stageDurations reparte el plazo en procesamiento, hasta despacho, tránsito y total", () => {
  assert.deepEqual(stageDurations(STAGES), { processing: 1, toShip: 11, transit: 3, total: 15 });
});

test("stageDurations devuelve null en lo que no se puede calcular", () => {
  assert.deepEqual(stageDurations([]), { processing: null, toShip: null, transit: null, total: null });
  const partial = stageDurations(STAGES.slice(0, 3));
  assert.equal(partial.transit, null);
  assert.equal(partial.total, null);
  assert.equal(partial.toShip, 11);
});

test("stageLabel y ticketTypeLabel traducen lo conocido y limpian lo desconocido", () => {
  assert.equal(stageLabel("out_for_delivery"), "En reparto");
  assert.equal(stageLabel("customs_hold"), "customs hold");
  assert.equal(ticketTypeLabel("compliance_question"), "Consulta de cumplimiento");
  assert.equal(ticketTypeLabel("refund_request"), "refund request");
});
