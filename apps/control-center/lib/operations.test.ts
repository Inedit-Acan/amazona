import assert from "node:assert/strict";
import { test } from "node:test";
import { ticketTriage, ticketTypeLabel } from "./operations.ts";

test("ticketTypeLabel traduce lo conocido y limpia lo desconocido", () => {
  assert.equal(ticketTypeLabel("compliance_question"), "Consulta de cumplimiento");
  assert.equal(ticketTypeLabel("refund_request"), "refund request");
});

test("ticketTriage distingue lo que resuelve la IA de lo que escala", () => {
  assert.deepEqual(ticketTriage({ ticket_type: "order_status_inquiry", ai_resolvable: true, escalation_reason: null }), {
    label: "Resoluble por IA",
    detail: "Consulta de estado del pedido",
  });
  assert.deepEqual(ticketTriage({ ticket_type: "compliance_question", ai_resolvable: false, escalation_reason: "needs legal review" }), {
    label: "Escala a una persona",
    detail: "needs legal review",
  });
});
