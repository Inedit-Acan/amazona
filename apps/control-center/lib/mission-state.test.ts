import assert from "node:assert/strict";
import test from "node:test";

import type { Decision, MissionSummary } from "./api.ts";
import { blockerText, currentDecision, missionHeadline, missionLabel, missionOf, missionTone } from "./mission-state.ts";
import { readMission } from "./nexus-mission.ts";
import { fakeMissionSource } from "./nexus-test-support.ts";
import { missionPanel, readMissionTaskAgents, taskAgentPanel, type MissionTasksSource } from "./task-agent-reads.ts";

// El estado de una misión y su historia de decisiones (M50, Commit 9). Solo visibilidad: el backend decide y la interfaz lo cuenta. Un contrato
// roto NUNCA se lee como «completa», y una misión con varias decisiones enseña la vigente, no la primera de la lista.

const base = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  project_id: "p1",
  state: "ready_to_resume",
  resumable: true,
  resumed: false,
  blockers: [],
  pending_tasks: ["supplier_sourcing", "decision_synthesis"],
  completed_tasks: ["product_validation"],
  current_decision_id: "d1",
  decisions: 1,
  ...over,
});

const mission = (over: Record<string, unknown> = {}): MissionSummary => {
  const parsed = missionOf(base(over));
  assert.notEqual(parsed, null);
  return parsed as MissionSummary;
};

test("M50 · el contrato del estado de la misión se acepta tal cual lo envía el backend", () => {
  const parsed = mission({ state: "recovery_pending", resumable: false, blockers: [{ task: "product_validation", reason: "failed_recoverable" }] });
  assert.equal(parsed.state, "recovery_pending");
  assert.deepEqual(parsed.blockers, [{ task: "product_validation", reason: "failed_recoverable" }]);
});

test("M50 · un contrato roto es `null` (sin dato), nunca «completa»", () => {
  for (const bad of [
    null,
    "complete",
    base({ state: "done" }),
    base({ state: undefined }),
    base({ resumable: "yes" }),
    base({ blockers: "none" }),
    base({ blockers: [{ task: "t", reason: "weird" }] }),
    base({ blockers: [{ reason: "running" }] }),
    base({ pending_tasks: [1] }),
    base({ decisions: -1 }),
    base({ decisions: 1.5 }),
    base({ current_decision_id: 7 }),
    base({ project_id: "" }),
  ]) {
    assert.equal(missionOf(bad), null, JSON.stringify(bad));
  }
});

test("M50 · una misión sin decisión actual (`null`) es válida: aún no se ha decidido nada", () => {
  assert.equal(missionOf(base({ current_decision_id: null, decisions: 0 }))?.current_decision_id, null);
});

test("M50 · los cinco estados tienen su palabra: incompleta, recuperación pendiente, lista para reanudar, reanudando, reanudada", () => {
  assert.equal(missionHeadline(mission({ state: "recovery_pending" })), "Misión incompleta");
  assert.equal(missionLabel(mission({ state: "recovery_pending" })), "Recuperación pendiente");
  assert.equal(missionLabel(mission({ state: "ready_to_resume" })), "Lista para reanudar");
  assert.equal(missionLabel(mission({ state: "resuming" })), "Reanudando");
  assert.equal(missionLabel(mission({ state: "complete", resumed: true, resumable: false })), "Reanudada");
});

test("M50 · una misión completa que nunca se reanudó no lleva ni titular ni etiqueta", () => {
  const complete = mission({ state: "complete", resumable: false });
  assert.equal(missionHeadline(complete), null);
  assert.equal(missionLabel(complete), null);
  assert.equal(missionTone(complete), "neutral");
});

test("M50 · el tono: pendiente de recuperar es rojo; lista y en curso, ámbar; reanudada, verde; cancelada, neutra", () => {
  assert.equal(missionTone(mission({ state: "recovery_pending" })), "bad");
  assert.equal(missionTone(mission({ state: "ready_to_resume" })), "warn");
  assert.equal(missionTone(mission({ state: "resuming" })), "warn");
  assert.equal(missionTone(mission({ state: "complete", resumed: true })), "ok");
  assert.equal(missionTone(mission({ state: "cancelled" })), "neutral");
});

test("M50 · cada motivo que impide reanudar se escribe en llano, con la tarea", () => {
  const reasons = ["failed_recoverable", "failed_reassign_required", "failed_definitive", "unknown_agent", "mismatch", "no_agent_available", "running"] as const;
  const texts = reasons.map((reason) => blockerText({ task: "supplier_sourcing", reason }));
  assert.ok(texts.every((text) => text.startsWith("supplier_sourcing: ")));
  assert.equal(new Set(texts).size, reasons.length);
});

// --- La decisión vigente --------------------------------------------------------------------------------------------------------------

const decision = (id: string, over: Partial<Decision> = {}): Decision => ({
  id,
  project_id: "p1",
  status: "REVIEW",
  opportunity_score: 0,
  confidence: 0,
  rationale: null,
  correlation_id: "c1",
  evidence: [],
  ...over,
});

test("M50 · la decisión vigente es la marcada `is_current`, no la primera", () => {
  const list = [decision("d1", { version: 1, is_current: false }), decision("d2", { version: 2, is_current: true, supersedes_decision_id: "d1" })];
  const current = currentDecision(list);
  assert.equal(current.kind, "current");
  if (current.kind === "current") assert.equal(current.decision.id, "d2");
});

test("M50 · una sola decisión sin marcas (un backend anterior) es la vigente; ninguna es «ninguna»", () => {
  assert.equal(currentDecision([decision("d1")]).kind, "current");
  assert.equal(currentDecision([]).kind, "none");
});

test("M50 · varias decisiones sin una única marcada NO se adivinan: ambiguas", () => {
  assert.equal(currentDecision([decision("d1"), decision("d2")]).kind, "ambiguous");
  assert.equal(currentDecision([decision("d1", { is_current: true }), decision("d2", { is_current: true })]).kind, "ambiguous");
  assert.equal(currentDecision([decision("d1", { is_current: false }), decision("d2", { is_current: false })]).kind, "ambiguous");
});

test("M50 · readMission enseña la decisión vigente de una misión reanudada y conserva el error si no se sabe cuál", async () => {
  const project = { id: "p1", objective_id: "o1", name: "Misión", status: "VALIDATING" as const, created_at: "2026-10-18T10:00:00Z" };
  const resumed = await readMission(
    fakeMissionSource({
      projects: [project],
      decisions: { p1: [decision("d1", { is_current: false, version: 1 }), decision("d2", { is_current: true, version: 2, status: "GO" })] },
    }),
  );
  assert.equal(resumed.decision.kind, "loaded");
  if (resumed.decision.kind === "loaded") assert.equal(resumed.decision.data.id, "d2");

  const ambiguous = await readMission(fakeMissionSource({ projects: [project], decisions: { p1: [decision("d1"), decision("d2")] } }));
  assert.equal(ambiguous.decision.kind, "error");
});

// --- El panel de «Tareas y agentes» ---------------------------------------------------------------------------------------------------

const projectRow = { id: "p1", objective_id: "o1", name: "Misión", status: "VALIDATING" as const, created_at: "2026-10-18T10:00:00Z" };
const taskRow = {
  id: "t1",
  project_id: "p1",
  name: "product_validation",
  capability: "market_validation",
  status: "COMPLETED",
  input: null,
  output: null,
  error: null,
  depends_on: [],
  assigned_agent_id: null,
  agent_relation: null,
};

const tasksSource = (getMission?: MissionTasksSource["getMission"]): MissionTasksSource => ({
  listProjects: async () => [projectRow as never],
  listTasks: async () => [taskRow as never],
  getMission,
});

test("M50 · el panel lleva el estado de la misión cuando el backend lo envía", async () => {
  const read = await readMissionTaskAgents(
    tasksSource(async () => base({ state: "recovery_pending", resumable: false, blockers: [{ task: "product_validation", reason: "failed_recoverable" }] })),
  );
  const panel = taskAgentPanel(read, []);
  assert.equal(panel.kind, "loaded");
  if (panel.kind === "loaded") {
    assert.equal(panel.mission.kind, "loaded");
    if (panel.mission.kind === "loaded") {
      assert.equal(panel.mission.label, "Recuperación pendiente");
      assert.deepEqual(panel.mission.blockers, ["product_validation: falló y se puede reintentar"]);
    }
  }
});

test("M50 · si el estado de la misión no se puede leer, el panel dice «sin dato» y NO «completa»", async () => {
  for (const getMission of [undefined, async () => Promise.reject(new Error("boom")), async () => ({ state: "weird" })]) {
    const panel = taskAgentPanel(await readMissionTaskAgents(tasksSource(getMission)), []);
    assert.equal(panel.kind, "loaded");
    if (panel.kind === "loaded") assert.equal(panel.mission.kind, "unread");
  }
  assert.deepEqual(missionPanel(null), { kind: "unread" });
});
