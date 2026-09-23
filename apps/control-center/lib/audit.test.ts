import assert from "node:assert/strict";
import { test } from "node:test";
import { actorKind, eventCategory, isErrorAction, stateChanges } from "./audit.ts";

test("eventCategory clasifica por el prefijo de la acción", () => {
  assert.equal(eventCategory("project.created"), "Proyecto");
  assert.equal(eventCategory("decision.made"), "Decisión");
  assert.equal(eventCategory("approval.completed"), "Aprobación");
  assert.equal(eventCategory("pipeline_review.approved"), "Aprobación");
  assert.equal(eventCategory("memory.stored"), "Memoria");
  assert.equal(eventCategory("kill_switch.enabled"), "Seguridad");
  assert.equal(eventCategory("pipeline.run"), "Pipeline");
  assert.equal(eventCategory("economics.run"), "Análisis", "cualquier .run es un análisis");
  assert.equal(eventCategory("weird.thing"), "Otros");
});

test("actorKind deduce el tipo de actor de su nombre", () => {
  assert.equal(actorKind("agent-product-research-1"), "Agente");
  assert.equal(actorKind("ceo-orchestrator-1"), "Agente");
  assert.equal(actorKind("owner@amazona.local"), "Persona");
  assert.equal(actorKind("ceo"), "Orquestador");
  assert.equal(actorKind("system"), "Sistema");
});

test("isErrorAction detecta fallos y errores", () => {
  assert.equal(isErrorAction("task.failed"), true);
  assert.equal(isErrorAction("system.api_error"), true);
  assert.equal(isErrorAction("approval.completed"), false);
});

test("stateChanges empareja las claves de antes y después", () => {
  assert.deepEqual(stateChanges({ status: "pending", limit: null }, { status: "approved", limit: 1500 }), [
    { key: "limit", before: "null", after: "1500" },
    { key: "status", before: "pending", after: "approved" },
  ]);
  assert.deepEqual(stateChanges(null, { status: "APPROVED" }), [{ key: "status", before: null, after: "APPROVED" }]);
  assert.deepEqual(stateChanges(null, null), []);
});
