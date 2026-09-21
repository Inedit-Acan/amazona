import assert from "node:assert/strict";
import { test } from "node:test";
import type { AuditEntry } from "./api.ts";
import {
  actorKind,
  actorRows,
  auditSummary,
  eventCategory,
  filterEvents,
  groupByDay,
  isErrorAction,
  projectRows,
  stateChanges,
  unattributedCount,
  type AuditFilters,
} from "./audit.ts";

const entry = (over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: over.id ?? "e",
  actor: "ceo",
  action: "decision.made",
  resource: "decision:1",
  before: null,
  after: null,
  correlation_id: "c1",
  created_at: "2026-09-22T10:00:00",
  ...over,
});
const NOW = Date.parse("2026-09-22T12:00:00Z");
const ALL: AuditFilters = { window: "all", category: "all", actor: "all", project: "all", query: "" };
const projects = { c1: { id: "p1", name: "Auriculares" }, c2: { id: "p2", name: "Organizador" } };

test("eventCategory clasifica por prefijo de la acción", () => {
  assert.equal(eventCategory("project.created"), "Proyecto");
  assert.equal(eventCategory("task.completed"), "Proyecto");
  assert.equal(eventCategory("decision.made"), "Decisión");
  assert.equal(eventCategory("approval.approve"), "Aprobación");
  assert.equal(eventCategory("pipeline_review.approve"), "Aprobación");
  assert.equal(eventCategory("economics.run"), "Análisis");
  assert.equal(eventCategory("pipeline.run"), "Pipeline");
  assert.equal(eventCategory("memory.remember"), "Memoria");
  assert.equal(eventCategory("cosa.rara"), "Otros");
});

test("actorKind deduce el tipo de actor y isErrorAction detecta fallos", () => {
  assert.equal(actorKind("agent-legal-1"), "Agente");
  assert.equal(actorKind("pipeline-orchestrator-1"), "Agente");
  assert.equal(actorKind("owner@amazona.local"), "Persona");
  assert.equal(actorKind("ceo"), "Orquestador");
  assert.equal(actorKind("memory"), "Sistema");
  assert.equal(isErrorAction("task.failed"), true);
  assert.equal(isErrorAction("task.completed"), false);
});

test("filterEvents aplica periodo, tipo, actor, proyecto y texto", () => {
  const list = [
    entry({ id: "a", created_at: "2026-09-22T10:00:00" }),
    entry({ id: "b", action: "approval.approve", actor: "owner@amazona.local", correlation_id: "c2", created_at: "2026-09-10T10:00:00" }),
    entry({ id: "c", action: "economics.run", actor: "agent-economic-1", correlation_id: "c3", created_at: "2026-08-01T10:00:00" }),
  ];
  const ids = (f: Partial<AuditFilters>) => filterEvents(list, { ...ALL, ...f }, projects, NOW).map((e) => e.id);
  assert.deepEqual(ids({}), ["a", "b", "c"]);
  assert.deepEqual(ids({ window: "24h" }), ["a"]);
  assert.deepEqual(ids({ window: "30d" }), ["a", "b"]);
  assert.deepEqual(ids({ category: "Aprobación" }), ["b"]);
  assert.deepEqual(ids({ actor: "agent-economic-1" }), ["c"]);
  assert.deepEqual(ids({ project: "p2" }), ["b"]);
  assert.deepEqual(ids({ query: "organizador" }), ["b"]);
  assert.deepEqual(ids({ query: "ECONOMICS" }), ["c"]);
});

test("auditSummary cuenta totales, hoy, aprobaciones, decisiones, errores y actores", () => {
  const summary = auditSummary(
    [
      entry({ id: "1" }),
      entry({ id: "2", action: "approval.approve", actor: "owner@amazona.local", created_at: "2026-09-20T10:00:00" }),
      entry({ id: "3", action: "task.failed", actor: "agent-x" }),
    ],
    NOW,
  );
  assert.deepEqual(summary, { total: 3, today: 2, approvals: 1, decisions: 1, errors: 1, actors: 3 });
});

test("actorRows y projectRows agrupan y ordenan; unattributedCount cuenta los sin proyecto", () => {
  const list = [
    entry({ id: "1", actor: "ceo", created_at: "2026-09-22T09:00:00" }),
    entry({ id: "2", actor: "ceo", created_at: "2026-09-22T11:00:00" }),
    entry({ id: "3", actor: "agent-a", correlation_id: "c2", created_at: "2026-09-22T10:00:00", action: "task.failed" }),
    entry({ id: "4", actor: "agent-a", correlation_id: "zzz" }),
  ];
  const actors = actorRows(list);
  assert.deepEqual(actors.map((a) => [a.actor, a.events, a.errors]), [["agent-a", 2, 1], ["ceo", 2, 0]]);
  assert.equal(actors.find((a) => a.actor === "ceo")?.lastAt, Date.parse("2026-09-22T11:00:00Z"));
  const byProject = projectRows(list, projects);
  assert.deepEqual(byProject.map((p) => [p.name, p.events, p.correlations]), [["Auriculares", 2, 1], ["Organizador", 1, 1]]);
  assert.equal(unattributedCount(list, projects), 1);
});

test("groupByDay agrupa por día local con lo más reciente primero", () => {
  const groups = groupByDay([
    entry({ id: "old", created_at: "2026-09-20T12:00:00Z" }),
    entry({ id: "new1", created_at: "2026-09-22T12:00:00Z" }),
    entry({ id: "new2", created_at: "2026-09-22T12:30:00Z" }),
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].entries.map((e) => e.id), ["new2", "new1"]);
  assert.deepEqual(groups[1].entries.map((e) => e.id), ["old"]);
});

test("stateChanges une las claves de antes y después", () => {
  assert.deepEqual(stateChanges({ status: "PENDING", a: 1 }, { status: "APPROVED", b: true }), [
    { key: "a", before: "1", after: null },
    { key: "b", before: null, after: "true" },
    { key: "status", before: "PENDING", after: "APPROVED" },
  ]);
  assert.deepEqual(stateChanges(null, null), []);
});
